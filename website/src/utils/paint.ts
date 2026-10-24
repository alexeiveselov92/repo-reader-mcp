/*
 * paint.ts — colour the landing page's terminal panels at build time. Each panel holds text as the server or a shell
 * prints it; these helpers escape it, colour each line by its shape and wrap it in a block, so the page ships HTML and
 * no script.
 */

const esc = (text: string): string => text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
const span = (cls: string, html: string): string => `<span class="${cls}">${html}</span>`;
const line = (html: string, cls = ''): string => `<span class="ln${cls ? ' ' + cls : ''}">${html || ' '}</span>`;

/** `[hidden: …]` marks, made visible as such. */
const hidden = (html: string): string => html.replace(/\[hidden: [^\]]+\]/g, (mark) => span('t-hidden', mark));

type Value = string | number | boolean;

/** A tool call as an agent makes it: `→ blame(repo="shop", start_line=18)`. */
export function call(tool: string, args: Record<string, Value> = {}): string {
  const shown = Object.entries(args)
    .map(([key, value]) =>
      typeof value === 'string' ? `${key}=${span('t-str', esc(JSON.stringify(value)))}` : `${key}=${span('t-num', String(value))}`,
    )
    .join(', ');
  return line(`${span('t-arrow', '→')} ${span('t-fn', tool)}(${shown})`, 't-call');
}

/** One line of a tool's answer, coloured by what it is. */
function answerLine(raw: string): string {
  const h = esc(raw);
  let m: RegExpMatchArray | null;
  // Where the answer read: the repository, the ref and the commit — or a search's summary.
  if ((/ · /.test(raw) && / @ [0-9a-f]{12}|· commit [0-9a-f]{12}/.test(raw) && !raw.startsWith('## ')) || /^`[^`]+` in \d+ repositor/.test(raw)) {
    return line(hidden(h), 't-head');
  }
  if (raw.startsWith('## ')) return line(h, 't-repo');
  if (/^=== .* ===$/.test(raw) || /^--- .* ---$/.test(raw)) return line(h, 't-guide');
  if (/^\[.*\]$/.test(raw)) return line(h, 't-note');
  // blame: the commit a group of lines last changed in
  if ((m = raw.match(/^([0-9a-f]{12}) (\d{4}-\d\d-\d\d .*)$/))) return line(`${span('t-id', m[1])} ${span('t-dim', esc(m[2]))}`);
  // log: one commit a row
  if ((m = raw.match(/^([0-9a-f]{12})(  \d{4}-\d\d-\d\d  )(.*?  )(.*)$/))) {
    return line(`${span('t-id', m[1])}${span('t-dim', m[2])}${span('t-dim', esc(m[3]))}${esc(m[4])}`);
  }
  // a numbered line of a file
  if ((m = raw.match(/^(\s*\d+)(\t.*)$/))) return line(`${span('t-dim', m[1])}${hidden(esc(m[2]))}`);
  // search and grep: a match (`12:`) or a line around it (`11-`)
  if ((m = raw.match(/^(\s+\d+)([:-])( .*)$/))) {
    return m[2] === ':'
      ? line(`${span('t-dim', m[1] + ':')}${hidden(esc(m[3]))}`)
      : line(span('t-dim', esc(raw)));
  }
  // a changed file: A added, M modified, D deleted
  if ((m = raw.match(/^(  )([AMDT])(  .*)$/))) {
    const tone = { A: 't-add', M: 't-mod', D: 't-del', T: 't-mod' }[m[2]];
    return line(`${m[1]}${span(tone!, m[2])}${esc(m[3])}`);
  }
  if (/^(diff --git|index |--- |\+\+\+ |new file)/.test(raw)) return line(h, 't-dim');
  if (raw.startsWith('@@')) return line(h, 't-hunk');
  if (raw.startsWith('+')) return line(h, 't-add');
  if (raw.startsWith('-') && !raw.startsWith('- `')) return line(h, 't-del'); // not a list of guidance pieces
  if ((m = raw.match(/^(Author|Parent|Parents|Committer):(.*)$/))) return line(`${span('t-dim', m[1] + ':')}${esc(m[2])}`);
  if (/^ {4}\S/.test(raw)) return line(h, 't-msg');
  if (/ is outside what this server serves/.test(raw)) return line(h, 't-refused');
  return line(hidden(h));
}

/** A tool's answer, as the server writes it. */
export function answer(text: string): string {
  return text.split('\n').map(answerLine).join('');
}

/** A YAML file: keys, strings and comments. */
export function yaml(text: string): string {
  return text
    .split('\n')
    .map((raw) => {
      const at = raw.search(/(^|\s)#/);
      const code = at === -1 ? raw : raw.slice(0, at);
      const comment = at === -1 ? '' : raw.slice(at);
      // strings first: the spans the other two add carry quotes of their own
      let h = esc(code)
        .replace(/"[^"]*"/g, (s) => span('t-str', s))
        .replace(/^(\s*(?:- )?)([A-Za-z_][\w.-]*)(:)/, (_, lead, key, colon) => `${lead}${span('t-key', key)}${colon}`)
        .replace(/(:\s+)(\d+)(\s*)$/, (_, sep, n, tail) => `${sep}${span('t-num', n)}${tail}`);
      if (comment) h += span('t-comment', esc(comment));
      return line(h);
    })
    .join('');
}

/** A shell session: `$ ` commands (a line starting with spaces continues one) and `# ` comments. */
export function shell(text: string): string {
  return text
    .split('\n')
    .map((raw) => {
      if (raw.startsWith('$ ')) {
        const rest = raw.slice(2);
        const at = rest.search(/\s#\s/);
        const cmd = at === -1 ? rest : rest.slice(0, at);
        const comment = at === -1 ? '' : rest.slice(at);
        return line(`${span('t-prompt', '$')} ${esc(cmd)}${comment ? span('t-comment', esc(comment)) : ''}`, 't-cmd');
      }
      if (raw.startsWith('#')) return line(esc(raw), 't-comment');
      if (/^\s+\S/.test(raw)) return line(esc(raw), 't-cont');
      return line(esc(raw));
    })
    .join('');
}

/** What `--check` prints about a group: what the host lists, what it takes, what it leaves out and why. */
export function check(text: string): string {
  return text
    .split('\n')
    .map((raw) => {
      const h = esc(raw);
      if (/^\s+left out: /.test(raw)) {
        return line(h.replace(/(: )(archived|skipped)$/, (_, sep, why) => `${sep}${span('t-mod', why)}`), 't-dim');
      }
      if (raw.endsWith('(mirror made)')) return line(h.replace('(mirror made)', span('t-add', '(mirror made)')));
      if (raw.endsWith('(not mirrored yet)')) return line(h.replace('(not mirrored yet)', span('t-mod', '(not mirrored yet)')));
      if (/^\s+(github|gitlab): /.test(raw)) return line(h, 't-repo');
      if (raw.trim() === '…') return line(h, 't-dim');
      return line(h);
    })
    .join('');
}

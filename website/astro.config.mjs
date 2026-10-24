// @ts-check
import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';

// The guide's pages come from docs/ (scripts/sync-docs.mjs); the sidebar lists them in the order a reader meets them.
export default defineConfig({
  site: 'https://rrm.pipelab.dev',
  integrations: [
    starlight({
      title: 'repo-reader-mcp',
      description:
        'A read-only MCP server for code in git repositories: files at any branch, tag or commit, history, diffs and blame — for any MCP client and any code host.',
      favicon: '/favicon.svg',
      customCss: ['./src/styles.css'],
      social: [{ icon: 'github', label: 'GitHub', href: 'https://github.com/alexeiveselov92/repo-reader-mcp' }],
      lastUpdated: false,
      sidebar: [
        { label: 'Getting started', link: '/getting-started/' },
        {
          label: 'Guides',
          items: [
            { label: 'Remote repositories', link: '/remote-repositories/' },
            { label: 'Running it for a team', link: '/serving-over-http/' },
            { label: 'Running it in a container', link: '/running-in-a-container/' },
          ],
        },
        {
          label: 'Reference',
          items: [
            { label: 'Tools', link: '/reference/tools/' },
            { label: 'Configuration', link: '/reference/configuration/' },
            { label: 'Guidance for agents', link: '/reference/guidance/' },
            { label: 'Safety', link: '/reference/safety/' },
          ],
        },
        { label: 'About this guide', link: '/guide/' },
        { label: 'Changelog', link: '/changelog/' },
      ],
    }),
  ],
});

import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';

export default defineConfig({
  site: 'https://juan-campuzano.github.io',
  base: '/minifactory',
  integrations: [
    starlight({
      title: 'minifactory',
      description: 'A tiny, pluggable software factory: declarative workflows made of plugin steps.',
      logo: {
        light: './src/assets/minifactory-horizontal-light.svg',
        dark: './src/assets/minifactory-horizontal-dark.svg',
        replacesTitle: true,
      },
      favicon: '/favicon.svg',
      social: {
        github: 'https://github.com/juan-campuzano/minifactory',
      },
      customCss: ['./src/styles/custom.css'],
      sidebar: [
        {
          label: 'Guides',
          items: [
            { label: 'Getting Started', slug: 'guides/getting-started' },
            { label: 'Workspaces & Config', slug: 'guides/workspaces' },
            { label: 'CLI Reference', slug: 'guides/cli' },
          ],
        },
        {
          label: 'Specifications',
          items: [
            { label: 'Workflow YAML Format', slug: 'specs/workflows' },
            { label: 'Role Profiles & LLMs', slug: 'specs/roles' },
            { label: 'Stack Profiles', slug: 'specs/stacks' },
            { label: 'Skills (SKILL.md)', slug: 'specs/skills' },
            { label: 'Writing Plugins', slug: 'specs/plugins' },
          ],
        },
        {
          label: 'Reference',
          items: [
            { label: 'Workflow Templates', slug: 'reference/templates' },
            { label: 'Steps & Plugins Catalog', slug: 'reference/catalog' },
          ],
        },
      ],
    }),
  ],
});

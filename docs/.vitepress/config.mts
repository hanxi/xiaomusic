import { defineConfig } from 'vitepress'
import AutoSidebar from 'vite-plugin-vitepress-auto-sidebar';
import GitHubIssuesPlugin from './vitepress-plugin-github-issues.mts';

// https://vitepress.dev/reference/site-config
export default defineConfig({
  title: "XiaoMusic",
  description: "XiaoMusic doc",
  themeConfig: {
    // https://vitepress.dev/reference/default-theme-config
    nav: [
      { text: 'Home', link: '/' },
      { text: 'Examples', link: '/markdown-examples' }
    ],

    socialLinks: [
      { icon: 'github', link: 'https://github.com/hanxi/xiaomusic' }
    ]
  },
  sitemap: {
    hostname: 'https://docs.x.hanxi.cc'
  },
  lastUpdated: true,
	markdown: {
    lineNumbers: false, // 关闭代码块行号显示
    // 自定义 markdown-it 插件
    config: (md) => {
      md.renderer.rules.link_open = (tokens, idx, options, env, self) => {
        const aIndex = tokens[idx].attrIndex('target');
        if (aIndex < 0) {
          tokens[idx].attrPush(['target', '_self']); // 将默认行为改为不使用 _blank
        } else {
          tokens[idx].attrs![aIndex][1] = '_self'; // 替换 _blank 为 _self
        }
        return self.renderToken(tokens, idx, options);
      };
    },
  },
  logLevel: 'warn',
  vite:{
    plugins: [
      AutoSidebar({
        path:'.',
        collapsed: true,
				titleFromFile: true,
      }),
      GitHubIssuesPlugin({
        repo: 'hanxi/xiaomusic',
        token: '',
        replaceRules:[
          {
            baseUrl: 'https://github.com/hanxi/xiaomusic/issues',
            targetUrl: '/issues',
          },
        ],
      }),
    ],
  }
})

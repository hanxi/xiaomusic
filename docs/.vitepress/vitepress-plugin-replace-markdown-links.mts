import { Plugin } from 'vite';

interface ReplaceRule {
  baseUrl: string; // 要匹配的基地址
  targetUrl: string; // 替换后的目标地址
}

export default function replaceMarkdownLinks(rules: ReplaceRule[]): Plugin {
  return {
    name: 'vitepress-plugin-replace-markdown-links',
    transform(code, id) {
      // 仅处理 Markdown 文件
      if (id.endsWith('.md')) {
        let transformedCode = code;

        // 遍历所有替换规则
        rules.forEach(({ baseUrl, targetUrl }) => {
          // 将 baseUrl 转换为正则表达式，匹配后接的路径部分
          const pattern = new RegExp(`${baseUrl.replace(/[-/\\^$*+?.()|[\]{}]/g, '\\$&')}(/\\d+)`, 'g');
          // 替换为目标 URL
          transformedCode = transformedCode.replace(pattern, `${targetUrl}$1.html`);
        });

        return transformedCode;
      }
      return null; // 不处理其他文件
    },
  };
}


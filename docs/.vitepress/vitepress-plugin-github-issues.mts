import axios from 'axios';
import fs from 'fs';
import path from 'path';
import type { Plugin } from 'vitepress';

interface ReplaceRule {
  baseUrl: string;
  targetUrl: string;
}

interface GitHubIssuesPluginOptions {
  repo: string;
  token: string;
  replaceRules: ReplaceRule[];
  githubProxy: string;
}

// 增强超时 + 重试
axios.defaults.timeout = 15000;

async function fetchAllIssues(repo: string, token: string): Promise<any[]> {
  const maxRetries = 5;
  let attempt = 0;
  const allIssues: any[] = [];
  let page = 1;

  while (true) {
    try {
      const response = await axios.get(`https://api.github.com/repos/${repo}/issues`, {
        headers: { Authorization: `token ${token}` },
        params: { page, per_page: 100 },
      });

      if (response.data.length === 0) break;
      allIssues.push(...response.data);
      page++;
      attempt = 0;
    } catch (error: any) {
      attempt++;
      console.error(`[Issue 获取失败] page ${page}, 重试 ${attempt}/${maxRetries}`);
      if (attempt >= maxRetries) {
        console.error(`❌ 终止获取 Issue，已获取数量：${allIssues.length}`);
        break;
      }
      await new Promise(r => setTimeout(r, 3000 * attempt));
    }
  }
  return allIssues;
}

async function fetchIssueComments(repo: string, issueNumber: number, token: string): Promise<any[]> {
  const maxRetries = 3;
  let attempt = 0;
  const allComments: any[] = [];
  let page = 1;

  while (attempt < maxRetries) {
    try {
      const res = await axios.get(
        `https://api.github.com/repos/${repo}/issues/${issueNumber}/comments`,
        {
          headers: { Authorization: `token ${token}` },
          params: { page, per_page: 100 },
        }
      );
      if (res.data.length === 0) break;
      allComments.push(...res.data);
      page++;
    } catch (err) {
      attempt++;
      if (attempt >= maxRetries) break;
      await new Promise(r => setTimeout(r, 2000));
    }
  }
  return allComments;
}

function clearDirectory(dir: string) {
  if (fs.existsSync(dir)) {
    fs.readdirSync(dir).forEach(file => {
      const p = path.join(dir, file);
      fs.lstatSync(p).isDirectory() ? clearDirectory(p) : fs.unlinkSync(p);
    });
  }
}

function copyFile(src: string, dest: string) {
  if (fs.existsSync(src)) fs.copyFileSync(src, dest);
}

function prependToFile(file: string, text: string) {
  if (!fs.existsSync(file)) return;
  const c = fs.readFileSync(file, 'utf8');
  fs.writeFileSync(file, `${text}\n\n${c}`);
}

function replaceGithubAssetUrls(content: string, proxy: string): string {
  return content
    .replace(/https:\/\/github\.com\/[^\/]+\/[^\/]+\/assets\/[\w-]+/g, m => m.replace('https://github.com', proxy))
    .replace(/https:\/\/github\.com\/user-attachments\/assets\/[\w-]+/g, m => m.replace('https://github.com', proxy));
}

// 核心修复：生成空文件占位，防止构建报错
function ensureIssueFile(number: number, dir: string, htmlUrl: string) {
  const file = path.join(dir, `${number}.md`);
  if (fs.existsSync(file)) return;

  const content = `---
title: Issue #${number} (加载失败)
---
# Issue #${number} 加载失败

原因：GitHub API 请求失败 / 网络超时

[前往查看](${htmlUrl})
`;
  fs.writeFileSync(file, content, 'utf8');
  console.log(`⚠️ 自动生成占位文件：${file}`);
}

export default function GitHubIssuesPlugin(options: GitHubIssuesPluginOptions): Plugin {
  const { repo, token, replaceRules, githubProxy } = options;

  return {
    name: 'vitepress-plugin-github-issues',

    async buildStart() {
      console.log('🚀 开始从 GitHub Issues 生成文档...');

      try {
        const issues = await fetchAllIssues(repo, token);
        console.log(`✅ 成功获取 Issue 数量：${issues.length}`);

        const issuesDir = path.join(process.cwd(), 'issues');
        clearDirectory(issuesDir);
        if (!fs.existsSync(issuesDir)) fs.mkdirSync(issuesDir);

        // 复制 README / CHANGELOG
        copyFile(path.join(process.cwd(), '../README.md'), path.join(issuesDir, 'index.md'));
        copyFile(path.join(process.cwd(), '../CHANGELOG.md'), path.join(issuesDir, 'changelog.md'));
        prependToFile(path.join(issuesDir, 'changelog.md'), '# 版本日志');

        // 遍历处理 Issue
        for (const issue of issues) {
          try {
            const hasDocLabel = issue.labels?.some(l => l.name === '文档');
            if (!hasDocLabel) continue;

            const comments = await fetchIssueComments(repo, issue.number, token);
            const title = issue.title.replace(/[\/\\?%*:|"<>]/g, '-');
            const fileName = `${issue.number}.md`;

            let content = `---
title: ${issue.title}
---
# ${title}
${issue.body || '无内容'}
## 评论
`;

            comments.forEach((c, i) => {
              content += `\n### 评论 ${i + 1} - ${c.user.login}\n${c.body}\n---\n`;
            });

            replaceRules.forEach(({ baseUrl, targetUrl }) => {
              const reg = new RegExp(`${baseUrl.replace(/[-/\\^$*+?.()|[\]{}]/g, '\\$&')}(/\\d+)`, 'g');
              content = content.replace(reg, `${targetUrl}$1.html`);
            });

            content = replaceGithubAssetUrls(content, githubProxy);
            content += `\n[Issue 链接](${issue.html_url})\n`;

            fs.writeFileSync(path.join(issuesDir, fileName), content, 'utf8');
            console.log(`✅ 生成：${fileName}`);
          } catch (e) {
            console.error(`❌ 处理 Issue #${issue.number} 失败：`, e);
            ensureIssueFile(issue.number, issuesDir, issue.html_url); // 自动生成占位文件
          }
        }

        console.log('🎉 所有 Issue 文档生成完成（失败项已自动占位）');
      } catch (e) {
        console.error('💥 整体流程异常：', e);
      }
    },
  };
}

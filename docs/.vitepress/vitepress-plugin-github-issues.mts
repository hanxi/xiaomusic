// vitepress-plugin-github-issues.mts

import axios from 'axios';
import fs from 'fs';
import path from 'path';
import type { Plugin } from 'vitepress';

interface ReplaceRule {
  baseUrl: string; // 要匹配的基地址
  targetUrl: string; // 替换后的目标地址
}

interface GitHubIssuesPluginOptions {
  repo: string; // GitHub repository info in the format 'owner/repo'
  token: string;
  replaceRules: ReplaceRule[];
  githubProxy: string;
}

async function fetchAllIssues(repo: string, token: string): Promise<any[]> {
  const maxRetries = 3; // 最大重试次数
  let attempt = 0;
  const allIssues: any[] = [];
  let page = 1;

  while (true) {
    while (attempt < maxRetries) {
      try {
        const response = await axios.get(`https://api.github.com/repos/${repo}/issues`, {
          headers: {
            Authorization: `token ${token}`
          },
          params: {
            page: page,
            per_page: 100 // 每页最多返回100条记录
          }
        });

        // 如果没有更多问题了，退出循环
        if (response.data.length === 0) {
          return allIssues;
        }

        allIssues.push(...response.data);
        page++; // 下一页
        attempt = 0; // 重置尝试次数
        break; // 退出尝试循环
      } catch (error) {
        if (error.response && error.response.status === 503) {
          console.error(`服务不可用, 正在重试...`);
          attempt++;
          const waitTime = Math.pow(2, attempt) * 1000; // 指数等待时间
          await new Promise(resolve => setTimeout(resolve, waitTime));
        } else {
          throw error; // 如果不是503错误，抛出错误并停止重试
        }
      }
    }

    if (attempt >= maxRetries) {
      throw new Error('最大重试次数已达，请检查 API 状态（可能是请求过于频繁）');
    }
  }
}

async function fetchIssueComments(repo: string, issueNumber: number, token: string): Promise<any[]> {
  const maxRetries = 3;
  let attempt = 0;
  const allComments: any[] = [];
  let page = 1;

  while (true) {
    while (attempt < maxRetries) {
      try {
        const response = await axios.get(
          `https://api.github.com/repos/${repo}/issues/${issueNumber}/comments`,
          {
            headers: {
              Authorization: `token ${token}`,
            },
            params: {
              page: page,
              per_page: 100,
            },
          }
        );

        if (response.data.length === 0) {
          return allComments; // 如果没有更多评论，退出循环
        }

        allComments.push(...response.data);
        page++;
        attempt = 0;
        break; // 成功获取评论数据，退出重试
      } catch (error: any) {
        if (error.response && error.response.status === 503) {
          console.error('服务不可用，正在重试...');
          attempt++;
          const waitTime = Math.pow(2, attempt) * 1000;
          await new Promise((resolve) => setTimeout(resolve, waitTime));
        } else {
          throw error;
        }
      }
    }

    if (attempt >= maxRetries) {
      throw new Error('最大重试次数已达，请检查 API 状态（可能是请求过于频繁）');
    }
  }
}

function clearDirectory(dir: string) {
  if (fs.existsSync(dir)) {
    fs.readdirSync(dir).forEach((file) => {
      const filePath = path.join(dir, file);
      if (fs.lstatSync(filePath).isDirectory()) {
        clearDirectory(filePath); // 递归清理子目录
        fs.rmdirSync(filePath);
      } else {
        fs.unlinkSync(filePath); // 删除文件
      }
    });
    console.log(`Cleared directory: ${dir}`);
  }
}

function copyFile(source: string, destination: string) {
  if (fs.existsSync(source)) {
    fs.copyFileSync(source, destination);
    console.log(`Copied file from ${source} to ${destination}`);
  } else {
    console.error(`file not found at ${source}`);
  }
}

// 在文件开头插入内容
function prependToFile(filePath: string, text: string) {
    const content = fs.readFileSync(filePath, 'utf-8');
    const updatedContent = `${text}\n\n${content}`;
    fs.writeFileSync(filePath, updatedContent, 'utf-8');
    console.log(`Prepended text to ${filePath}`);
}

function replaceGithubAssetUrls(content: string, githubProxy: string): string {
    const pattern1 = /https:\/\/github\.com\/[^\/]+\/[^\/]+\/assets\/[\w-]+/g;
    const pattern2 = /https:\/\/github\.com\/user-attachments\/assets\/[\w-]+/g;

    // 使用正则表达式替换符合条件的链接
    const transformedContent = content.replace(pattern1, (match) => {
        return match.replace("https://github.com", githubProxy);
    }).replace(pattern2, (match) => {
        return match.replace("https://github.com", githubProxy);
    });

    return transformedContent;
}

export default function GitHubIssuesPlugin(options: GitHubIssuesPluginOptions): Plugin {
  const { repo, token, replaceRules, githubProxy } = options;

  return {
    name: 'vitepress-plugin-github-issues',

    async buildStart() {
      try {
        const issues = await fetchAllIssues(repo, token);

        console.log(`Fetched ${issues.length} issues from GitHub`); // Log the number of issues fetched

        const docsDir = path.join(process.cwd(), 'issues');

        // 清空 issues 目录
        clearDirectory(docsDir);

        // Create a directory to store markdown files if it doesn't exist
        if (!fs.existsSync(docsDir)) {
          fs.mkdirSync(docsDir);
          console.log(`Created docs directory: ${docsDir}`);
        }

        // 拷贝 ../README.md 文件到当前目录
        const readmeSource = path.join(process.cwd(), '../README.md');
        const readmeDestination = path.join(docsDir, 'index.md');
        copyFile(readmeSource, readmeDestination);

        // 拷贝 ../CHANGELOG.md 文件到当前目录
        const changelogSource = path.join(process.cwd(), '../CHANGELOG.md');
        const changelogDestination = path.join(docsDir, 'changelog.md');
        copyFile(changelogSource, changelogDestination);
        prependToFile(changelogDestination, '# 版本日志');

        for (const issue of issues) {
          // 仅处理包含 "文档" 标签的 issue
          const hasDocumentLabel = issue.labels.some(label => label.name === '文档');
          if (hasDocumentLabel) {
            const title = issue.title.replace(/[\/\\?%*:|"<>]/g, '-');
            const fileName = `${issue.number}.md`;

            // 获取评论数据
            const comments = await fetchIssueComments(repo, issue.number, token);

            let content =
              `---
title: ${issue.title}
---

# ${title}

${issue.body}

## 评论

`;

            // 插入评论
            if (comments.length > 0) {
              comments.forEach((comment, index) => {
                content += `
### 评论 ${index + 1} - ${comment.user.login}

${comment.body}

---
`;
              });
            } else {
              content += "没有评论。\n";
            }

            replaceRules.forEach(({ baseUrl, targetUrl }) => {
              // 将 baseUrl 转换为正则表达式，匹配后接的路径部分
              const pattern = new RegExp(`${baseUrl.replace(/[-/\\^$*+?.()|[\]{}]/g, '\\$&')}(/\\d+)`, 'g');
              // 替换为目标 URL
              content = content.replace(pattern, `${targetUrl}$1.html`);
            });

            content = replaceGithubAssetUrls(content, githubProxy);

            content += `[链接到 GitHub Issue](${issue.html_url})\n`;

            const filePath = path.join(docsDir, fileName);

            fs.writeFileSync(filePath, content, { encoding: 'utf8' });
            console.log(`Created file: ${filePath}`); // Log each created file
          } else {
            console.log(`Skipped issue: ${issue.title}`); // Log skipped issues
          }
        }

        console.log(`Successfully created markdown files from GitHub issues.`);
      } catch (error) {
        console.error('Error fetching GitHub issues:', error);
      }
    },
    };
}


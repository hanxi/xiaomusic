#!/usr/bin/env node

/**
 * JS 插件运行器
 * 在安全的沙箱环境中运行 MusicFree JS 插件
 */

const vm = require('vm');
const fs = require('fs');

// 设置编码
process.stdin.setEncoding('utf8');
process.stdout.setDefaultEncoding('utf8');

class PluginRunner {
    constructor() {
        this.plugins = new Map();
        this.requestId = 0;
        this.pendingRequests = new Map();
        this.setupMessageHandler();
    }

    setupMessageHandler() {
        let buffer = '';
        process.stdin.on('data', (data) => {
            buffer += data.toString();

            // 按行分割并处理完整的消息
            let lines = buffer.split('\n');
            buffer = lines.pop(); // 保留最后一行（可能不完整）

            for (const line of lines) {
                if (line.trim() === '') continue;
                try {
                    const message = JSON.parse(line.trim());
                    console.log(`[JS_PLUGIN_RUNNER] Raw message received: ${line.trim()}`);
                    this.handleMessage(message);
                } catch (error) {
                    console.error(`[JS_PLUGIN_RUNNER] Failed to parse message: ${line.trim()}`);
                    console.error(`[JS_PLUGIN_RUNNER] Error: ${error.message}`);
                    this.sendResponse('unknown', {
                        success: false,
                        error: `JSON parse error: ${error.message}`
                    });
                }
            }
        });
    }

    async handleMessage(message) {
        const { id, action } = message;
        // 只在必要时输出日志以避免干扰通信
        // console.debug(`[JS_PLUGIN_RUNNER] Received message: ${action} with id: ${id}`);
        // if (message.pluginName) console.debug(`[JS_PLUGIN_RUNNER] Plugin: ${message.pluginName}`);
        // if (message.params) console.debug(`[JS_PLUGIN_RUNNER] Params:`, message.params);
        // if (message.musicItem) console.debug(`[JS_PLUGIN_RUNNER] Music Item:`, message.musicItem);

        try {
            let result;
            switch (action) {
                case 'load':
                    console.log(`[JS_PLUGIN_RUNNER] Loading plugin: ${message.name}`);
                    result = this.loadPlugin(message.name, message.code);
                    break;
                case 'search':
                    result = await this.search(message.pluginName, message.params);
                    break;
                case 'getMediaSource':
                    result = await this.getMediaSource(message.pluginName, message.musicItem, message.quality);
                    break;
                case 'getLyric':
                    result = await this.getLyric(message.pluginName, message.musicItem);
                    break;
                case 'getMusicInfo':
                    result = await this.getMusicInfo(message.pluginName, message.musicItem);
                    break;
                case 'getAlbumInfo':
                    result = await this.getAlbum(message.pluginName, message.albumInfo);
                    break;
                case 'getMusicSheetInfo':
                    result = await this.getPlaylist(message.pluginName, message.playlistInfo);
                    break;
                case 'getArtistWorks':
                    result = await this.getArtistWorks(message.pluginName, message.artistItem, message.page, message.type);
                    break;
                case 'importMusicItem':
                    result = await this.importMusicItem(message.pluginName, message.urlLike);
                    break;
                case 'importMusicSheet':
                    result = await this.importMusicSheet(message.pluginName, message.urlLike);
                    break;
                case 'getTopLists':
                    result = await this.getTopLists(message.pluginName);
                    break;
                case 'getTopListDetail':
                    result = await this.getTopListDetail(message.pluginName, message.topListItem, message.page);
                    break;
                case 'unload':
                    console.log(`[JS_PLUGIN_RUNNER] Unloading plugin: ${message.name}`);
                    result = this.unloadPlugin(message.name);
                    break;
                default:
                    throw new Error(`Unknown action: ${action}`);
            }

            this.sendResponse(id, { success: true, result });
        } catch (error) {
            console.error(`[JS_PLUGIN_RUNNER] Action ${action} failed:`, error.message);
            this.sendResponse(id, { success: false, error: error.message });
        }
    }

    sendResponse(id, response) {
        response.id = id;
        process.stdout.write(JSON.stringify(response) + '\n');
    }

    loadPlugin(name, code) {
        try {
            // 创建安全的沙箱环境
            const sandbox = this.createSandbox();

            // 创建上下文
            const context = vm.createContext(sandbox);

            // 包装代码以支持 ES6 模块语法
            const wrappedCode = `
                (function() {
                    ${code}
                    // 如果是 TypeScript 编译的代码，需要处理 exports
                    if (typeof module !== 'undefined' && module.exports) {
                        return module.exports;
                    }
                    // 如果是 ES6 模块，需要处理 exports
                    if (typeof exports !== 'undefined' && exports.__esModule) {
                        return exports.default || exports;
                    }
                    return module.exports;
                })();
            `;

            // 执行插件代码
            const options = {
                timeout: 10000,
                displayErrors: true,
                breakOnSigint: false
            };

            const plugin = vm.runInContext(wrappedCode, context, options);

            // 验证插件接口
            if (!plugin || typeof plugin !== 'object') {
                throw new Error('Plugin must export an object');
            }

            this.plugins.set(name, plugin);

            // 记录插件信息
            this.plugins.set(name + '_meta', {
                loadTime: Date.now(),
                capabilities: this.detectCapabilities(plugin)
            });

            return true;
        } catch (error) {
            console.error(`Failed to load plugin ${name}:`, error.message);
            throw error;
        }
    }

    createSandbox() {
        const safeConsole = {
            log: (...args) => {},  // 禁用插件的 console.log 避免干扰主进程通信
            warn: (...args) => console.warn(`[PLUGIN]`, ...args),  // 保留警告，但添加标识
            error: (...args) => console.error(`[PLUGIN]`, ...args), // 保留错误，但添加标识
            debug: (...args) => {}  // 禁用调试输出
        };

        const safeFetch = async (url, options = {}) => {
            // 代理网络请求到主进程
            return await this.proxyFetch(url, options);
        };

        const safeTimer = (callback, delay) => {
            if (delay > 10000) { // 最大10秒
                throw new Error('Timer delay too long');
            }
            return setTimeout(callback, delay);
        };

        // 支持的模块列表
        const allowedModules = {
            'axios': require('axios'),
            'crypto-js': require('crypto-js'),
            'he': require('he'),
            'dayjs': require('dayjs'),
            'cheerio': require('cheerio'),
            'qs': require('qs')
        };

        const safeRequire = (moduleName) => {
            if (allowedModules[moduleName]) {
                return allowedModules[moduleName];
            }
            throw new Error(`Module '${moduleName}' is not allowed or not installed`);
        };

        const module = { exports: {} };
        const exports = module.exports;

        // 模拟 env 对象
        const env = {
            getUserVariables: () => ({
                music_u: '',
                ikun_key: '',
                source: ''
            })
        };

        return {
            // 基础对象
            console: safeConsole,
            Buffer: Buffer,
            Math: Math,
            Date: Date,
            JSON: JSON,

            // 受限的全局对象
            global: undefined,
            process: undefined,

            // 受限的网络访问
            fetch: safeFetch,
            XMLHttpRequest: undefined,

            // 受限的定时器
            setTimeout: safeTimer,
            setInterval: undefined,
            clearTimeout: clearTimeout,
            clearInterval: clearInterval,

            // 模块系统
            module: module,
            exports: exports,
            require: safeRequire,

            // MusicFree 环境对象
            env: env
        };
    }

    detectCapabilities(plugin) {
        const capabilities = [];
        if (typeof plugin.search === 'function') capabilities.push('search');
        if (typeof plugin.getMediaSource === 'function') capabilities.push('getMediaSource');
        if (typeof plugin.getLyric === 'function') capabilities.push('getLyric');
        if (typeof plugin.getAlbum === 'function') capabilities.push('getAlbum');
        if (typeof plugin.getPlaylist === 'function') capabilities.push('getPlaylist');
        return capabilities;
    }

    async search(pluginName, params) {
        const plugin = this.plugins.get(pluginName);
        if (!plugin) {
            throw new Error(`Plugin ${pluginName} not found`);
        }

        // 检查插件是否有 search 方法 - 参考 MusicFreeDesktop 实现
        if (!plugin.search || typeof plugin.search !== 'function') {
            // 只在详细模式下输出调试信息
            console.debug(`[JS_PLUGIN_RUNNER] Plugin ${pluginName} does not have a search function`);
            return {
                isEnd: true,
                data: []
            };
        }

        try {
            let query, page, type;
            if (typeof params === 'string') {
                // 兼容旧的字符串格式
                query = params;
                page = 1;
                type = 'music';
            } else if (typeof params === 'object') {
                // 新的对象格式，参考 MusicFreeDesktop
                query = params.keywords || params.query || '';
                page = params.page || 1;
                type = params.type || 'music';
            } else {
                throw new Error('Invalid search parameters');
            }

            // 移除调试输出，避免干扰 JSON 通信
            // console.debug(`[JS_PLUGIN_RUNNER] Calling search with query: ${query}, page: ${page}, type: ${type}`);
            const result = await plugin.search(query, page, type);

            // 将调试信息写入日志文件而不是控制台
            fs.appendFileSync('00-plugin_debug.log', `===========================${pluginName}插件原始返回结果：===================================\n`);
            fs.appendFileSync('00-plugin_debug.log', `${JSON.stringify(result, null, 2)}\n`);
            // 严格验证返回结果 - 参考 MusicFreeDesktop 实现
            if (!result || typeof result !== 'object') {
                console.error(`[JS_PLUGIN_RUNNER] Invalid search result from plugin ${pluginName}:`, typeof result);
                throw new Error(`Plugin ${pluginName} returned invalid search result`);
            }

            // 确保返回正确的数据结构 - 参考 MusicFreeDesktop 实现
            const validatedResult = {
                isEnd: result.isEnd !== false,  // 默认为 true，除非明确设置为 false
                data: Array.isArray(result.data) ? result.data : []  // 确保 data 是数组
            };
            //为 validatedResult中data的 每个元素添加一个 platform 属性
            validatedResult.data.forEach(item => {
                item.platform = pluginName;
            });
            // 不输出调试信息以避免干扰通信
            return validatedResult;
        } catch (error) {
            console.error(`[JS_PLUGIN_RUNNER] Search error in plugin ${pluginName}:`, error.message);
            // console.error(`[JS_PLUGIN_RUNNER] Full error:`, error);  // 避免输出可能包含非JSON的对象
            throw new Error(`Search failed in plugin ${pluginName}: ${error.message}`);
        }
    }


    async getMediaSource(pluginName, musicItem, quality) {
        const plugin = this.plugins.get(pluginName);
        if (!plugin) {
            throw new Error(`Plugin ${pluginName} not found`);
        }

        // 检查插件是否有 getMediaSource 方法 - 参考 MusicFreeDesktop 实现
        if (!plugin.getMediaSource || typeof plugin.getMediaSource !== 'function') {
            // 不输出调试信息以避免干扰通信
            return null;
        }

        try {
            const result = await plugin.getMediaSource(musicItem,quality);
            // 参考 MusicFreeDesktop 实现，验证结果
            if (result === null || result === undefined) {
                return null;
            }
            if (typeof result !== 'object') {
                console.error(`[JS_PLUGIN_RUNNER] Invalid media source result from plugin ${pluginName}:`, typeof result);
                throw new Error(`Plugin ${pluginName} returned invalid media source result`);
            }
            return result;
        } catch (error) {
            console.error(`[JS_PLUGIN_RUNNER] getMediaSource error in plugin ${pluginName}:`, error.message);
            throw new Error(`getMediaSource failed in plugin ${pluginName}: ${error.message}`);
        }
    }

    async getLyric(pluginName, songId) {
        const plugin = this.plugins.get(pluginName);
        if (!plugin) {
            throw new Error(`Plugin ${pluginName} not found`);
        }

        // 检查插件是否有 getLyric 方法 - 参考 MusicFreeDesktop 实现
        if (!plugin.getLyric || typeof plugin.getLyric !== 'function') {
            // 不输出调试信息以避免干扰通信
            return null;
        }

        try {
            const result = await plugin.getLyric(songId);
            // 参考 MusicFreeDesktop 实现，验证结果
            if (result === null || result === undefined) {
                return null;
            }
            if (typeof result !== 'object') {
                console.error(`[JS_PLUGIN_RUNNER] Invalid lyric result from plugin ${pluginName}:`, typeof result);
                throw new Error(`Plugin ${pluginName} returned invalid lyric result`);
            }
            return result;
        } catch (error) {
            console.error(`[JS_PLUGIN_RUNNER] getLyric error in plugin ${pluginName}:`, error.message);
            throw new Error(`getLyric failed in plugin ${pluginName}: ${error.message}`);
        }
    }

    async getAlbum(pluginName, albumInfo) {
        const plugin = this.plugins.get(pluginName);
        if (!plugin) {
            throw new Error(`Plugin ${pluginName} not found`);
        }

        // 检查插件是否有 getAlbumInfo 方法 (按照官方文档标准)
        if (!plugin.getAlbumInfo || typeof plugin.getAlbumInfo !== 'function') {
            // 不输出调试信息以避免干扰通信
            return null;
        }

        try {
            // 使用默认页码 1（从MusicFree官方文档得知默认为1）
            const result = await plugin.getAlbumInfo(albumInfo, 1);
            // 参考 MusicFree 实现，验证结果
            if (result === null || result === undefined) {
                return null;
            }
            if (typeof result !== 'object') {
                console.error(`[JS_PLUGIN_RUNNER] Invalid album result from plugin ${pluginName}:`, typeof result);
                throw new Error(`Plugin ${pluginName} returned invalid album result`);
            }
            return result;
        } catch (error) {
            console.error(`[JS_PLUGIN_RUNNER] getAlbumInfo error in plugin ${pluginName}:`, error.message);
            throw new Error(`getAlbumInfo failed in plugin ${pluginName}: ${error.message}`);
        }
    }

    async getPlaylist(pluginName, playlistInfo) {
        const plugin = this.plugins.get(pluginName);
        if (!plugin) {
            throw new Error(`Plugin ${pluginName} not found`);
        }

        // 检查插件是否有 getMusicSheetInfo 方法 (按照官方文档标准)
        if (!plugin.getMusicSheetInfo || typeof plugin.getMusicSheetInfo !== 'function') {
            // 不输出调试信息以避免干扰通信
            return null;
        }

        try {
            // 使用默认页码 1（从MusicFree官方文档得知默认为1）
            const result = await plugin.getMusicSheetInfo(playlistInfo, 1);
            // 参考 MusicFree 实现，验证结果
            if (result === null || result === undefined) {
                return null;
            }
            if (typeof result !== 'object') {
                console.error(`[JS_PLUGIN_RUNNER] Invalid playlist result from plugin ${pluginName}:`, typeof result);
                throw new Error(`Plugin ${pluginName} returned invalid playlist result`);
            }
            return result;
        } catch (error) {
            console.error(`[JS_PLUGIN_RUNNER] getMusicSheetInfo error in plugin ${pluginName}:`, error.message);
            throw new Error(`getMusicSheetInfo failed in plugin ${pluginName}: ${error.message}`);
        }
    }

    async getMusicInfo(pluginName, musicItem) {
        const plugin = this.plugins.get(pluginName);
        if (!plugin) {
            throw new Error(`Plugin ${pluginName} not found`);
        }

        // 检查插件是否有 getMusicInfo 方法 (按照官方文档标准)
        if (!plugin.getMusicInfo || typeof plugin.getMusicInfo !== 'function') {
            // 不输出调试信息以避免干扰通信
            return null;
        }

        try {
            const result = await plugin.getMusicInfo(musicItem);
            // 参考 MusicFree 实现，验证结果
            if (result === null || result === undefined) {
                return null;
            }
            if (typeof result !== 'object') {
                console.error(`[JS_PLUGIN_RUNNER] Invalid music info result from plugin ${pluginName}:`, typeof result);
                throw new Error(`Plugin ${pluginName} returned invalid music info result`);
            }
            return result;
        } catch (error) {
            console.error(`[JS_PLUGIN_RUNNER] getMusicInfo error in plugin ${pluginName}:`, error.message);
            throw new Error(`getMusicInfo failed in plugin ${pluginName}: ${error.message}`);
        }
    }

    async getArtistWorks(pluginName, artistItem, page = 1, type = 'music') {
        const plugin = this.plugins.get(pluginName);
        if (!plugin) {
            throw new Error(`Plugin ${pluginName} not found`);
        }

        // 检查插件是否有 getArtistWorks 方法 (按照官方文档标准)
        if (!plugin.getArtistWorks || typeof plugin.getArtistWorks !== 'function') {
            // 不输出调试信息以避免干扰通信
            return null;
        }

        try {
            const result = await plugin.getArtistWorks(artistItem, page, type);
            // 参考 MusicFree 实现，验证结果
            if (result === null || result === undefined) {
                return null;
            }
            if (typeof result !== 'object') {
                console.error(`[JS_PLUGIN_RUNNER] Invalid artist works result from plugin ${pluginName}:`, typeof result);
                throw new Error(`Plugin ${pluginName} returned invalid artist works result`);
            }
            return result;
        } catch (error) {
            console.error(`[JS_PLUGIN_RUNNER] getArtistWorks error in plugin ${pluginName}:`, error.message);
            throw new Error(`getArtistWorks failed in plugin ${pluginName}: ${error.message}`);
        }
    }

    async importMusicItem(pluginName, urlLike) {
        const plugin = this.plugins.get(pluginName);
        if (!plugin) {
            throw new Error(`Plugin ${pluginName} not found`);
        }

        // 检查插件是否有 importMusicItem 方法 (按照官方文档标准)
        if (!plugin.importMusicItem || typeof plugin.importMusicItem !== 'function') {
            // 不输出调试信息以避免干扰通信
            return null;
        }

        try {
            const result = await plugin.importMusicItem(urlLike);
            // 参考 MusicFree 实现，验证结果
            if (result === null || result === undefined) {
                return null;
            }
            if (typeof result !== 'object') {
                console.error(`[JS_PLUGIN_RUNNER] Invalid import music item result from plugin ${pluginName}:`, typeof result);
                throw new Error(`Plugin ${pluginName} returned invalid import music item result`);
            }
            return result;
        } catch (error) {
            console.error(`[JS_PLUGIN_RUNNER] importMusicItem error in plugin ${pluginName}:`, error.message);
            throw new Error(`importMusicItem failed in plugin ${pluginName}: ${error.message}`);
        }
    }

    async importMusicSheet(pluginName, urlLike) {
        const plugin = this.plugins.get(pluginName);
        if (!plugin) {
            throw new Error(`Plugin ${pluginName} not found`);
        }

        // 检查插件是否有 importMusicSheet 方法 (按照官方文档标准)
        if (!plugin.importMusicSheet || typeof plugin.importMusicSheet !== 'function') {
            // 不输出调试信息以避免干扰通信
            return null;
        }

        try {
            const result = await plugin.importMusicSheet(urlLike);
            // 参考 MusicFree 实现，验证结果
            if (result === null || result === undefined) {
                return null;
            }
            if (!Array.isArray(result)) {
                console.error(`[JS_PLUGIN_RUNNER] Invalid import music sheet result from plugin ${pluginName}:`, typeof result);
                throw new Error(`Plugin ${pluginName} returned invalid import music sheet result`);
            }
            return result;
        } catch (error) {
            console.error(`[JS_PLUGIN_RUNNER] importMusicSheet error in plugin ${pluginName}:`, error.message);
            throw new Error(`importMusicSheet failed in plugin ${pluginName}: ${error.message}`);
        }
    }

    async getTopLists(pluginName) {
        const plugin = this.plugins.get(pluginName);
        if (!plugin) {
            throw new Error(`Plugin ${pluginName} not found`);
        }

        // 检查插件是否有 getTopLists 方法 (按照官方文档标准)
        if (!plugin.getTopLists || typeof plugin.getTopLists !== 'function') {
            // 不输出调试信息以避免干扰通信
            return null;
        }

        try {
            const result = await plugin.getTopLists();
            // 参考 MusicFree 实现，验证结果
            if (result === null || result === undefined) {
                return null;
            }
            if (!Array.isArray(result)) {
                console.error(`[JS_PLUGIN_RUNNER] Invalid top lists result from plugin ${pluginName}:`, typeof result);
                throw new Error(`Plugin ${pluginName} returned invalid top lists result`);
            }
            return result;
        } catch (error) {
            console.error(`[JS_PLUGIN_RUNNER] getTopLists error in plugin ${pluginName}:`, error.message);
            throw new Error(`getTopLists failed in plugin ${pluginName}: ${error.message}`);
        }
    }

    async getTopListDetail(pluginName, topListItem, page = 1) {
        const plugin = this.plugins.get(pluginName);
        if (!plugin) {
            throw new Error(`Plugin ${pluginName} not found`);
        }

        // 检查插件是否有 getTopListDetail 方法 (按照官方文档标准)
        if (!plugin.getTopListDetail || typeof plugin.getTopListDetail !== 'function') {
            // 不输出调试信息以避免干扰通信
            return null;
        }

        try {
            const result = await plugin.getTopListDetail(topListItem, page);
            // 参考 MusicFree 实现，验证结果
            if (result === null || result === undefined) {
                return null;
            }
            if (typeof result !== 'object') {
                console.error(`[JS_PLUGIN_RUNNER] Invalid top list detail result from plugin ${pluginName}:`, typeof result);
                throw new Error(`Plugin ${pluginName} returned invalid top list detail result`);
            }
            return result;
        } catch (error) {
            console.error(`[JS_PLUGIN_RUNNER] getTopListDetail error in plugin ${pluginName}:`, error.message);
            throw new Error(`getTopListDetail failed in plugin ${pluginName}: ${error.message}`);
        }
    }

    unloadPlugin(name) {
        const deleted = this.plugins.delete(name);
        this.plugins.delete(name + '_meta');
        return deleted;
    }

    async proxyFetch(url, options) {
        // 代理网络请求到主进程
        const requestId = ++this.requestId;

        return new Promise((resolve, reject) => {
            // 发送请求到主进程
            this.sendResponse('fetch_' + requestId, {
                action: 'fetch',
                requestId: requestId,
                url: url,
                options: options
            });

            // 等待响应（简化实现）
            setTimeout(() => {
                reject(new Error('Fetch proxy not implemented'));
            }, 1000);
        });
    }
}

// 启动插件运行器
const runner = new PluginRunner();

// 处理进程退出
process.on('SIGINT', () => {
    // 不输出任何内容，避免干扰 JSON 通信
    process.exit(0);
});

process.on('SIGTERM', () => {
    // 不输出任何内容，避免干扰 JSON 通信
    process.exit(0);
});

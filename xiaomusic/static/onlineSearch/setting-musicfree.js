/*============================插件源相关函数=================================*/
// 加载 OpenAPI 配置
async function loadPluginSource() {
    const container = document.getElementById('plugin-source');
    if (!container) return;
    try {
        const response = await fetch('/api/plugin-source/load');
        const data = await response.json();
        if (data.success) {
            displayPluginSource(data.data);
        } else {
            container.innerHTML = `<div class="error">加载失败：${data.error}</div>`;
        }
    } catch (error) {
        container.innerHTML = `<div class="error">加载出错：${error.message}</div>`;
    }
}

// 显示 OpenAPI 配置
function displayPluginSource(config) {
    document.getElementById('source-url').textContent = config.source_url || '';
    const editButtonElement = document.getElementById('edit-source-btn');
    if (config.source_url && config.source_url.length > 0) {
        editButtonElement.style.display = 'inline-flex';
    }
}


// 刷新订阅源
async function refreshPluginSource() {
    try {
        const urlElement = document.getElementById('source-url');
        const currentUrl = urlElement.textContent;
        if (!currentUrl) {
            alert('请先设置接口地址！');
            return;
        }
        if (!confirm(`确定要刷新订阅源吗？相同名称插件将被覆盖！`)) {
            return;
        }
        const response = await fetch('/api/plugin-source/refresh', {
            method: 'POST'
        });
        const data = await response.json();

        if (data.success) {
            // 操作成功，重新加载插件列表
            await loadPlugins();
        } else {
            alert(`切换失败：${data.error}`);
        }
    } catch (error) {
        alert(`操作出错：${error.message}`);
    }
}

// 编辑插件订阅源地址
function editPluginSource() {
    const urlElement = document.getElementById('source-url');
    const currentUrl = urlElement.textContent;
    const newUrl = prompt('请输入新的插件源地址:', currentUrl);

    // 检查用户是否点击了取消
    if (newUrl === null) {
        // 用户点击了取消，不执行任何操作
        return;
    }

    // 检查用户是否输入了空字符串
    if (newUrl.trim() === '') {
        alert('插件源地址不能为空！');
        return;
    }

    // 校验 URL 格式
    const urlPattern = /^(https?:\/\/)?([\da-z.-]+)\.([a-z.]{2,6})([/\w .-]*)*\/?$/;
    if (urlPattern.test(newUrl)) {
        // 更新地址
        updatePluginSource(newUrl);
    } else {
        alert('请输入有效的插件源地址！');
    }
}

// 更新 OpenAPI 地址
async function updatePluginSource(newUrl) {
    try {
        const response = await fetch('/api/plugin-source/updateUrl', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ source_url: newUrl })
        });
        const data = await response.json();

        if (data.success) {
            // 更新成功，重新加载插件列表
            await loadPluginSource();
        } else {
            alert(`更新失败：${data.error}`);
        }
    } catch (error) {
        alert(`更新出错：${error.message}`);
    }
}

/*============================插件函数=================================*/

// 加载插件列表
async function loadPlugins() {
    const container = document.getElementById('plugins-container');
    container.innerHTML = '<div class="loading">加载中...</div>';

    try {
        const response = await fetch('/api/js-plugins');
        const data = await response.json();

        if (data.success) {
            displayPlugins(data.data);
        } else {
            container.innerHTML = `<div class="error">加载失败：${data.error}</div>`;
        }
    } catch (error) {
        container.innerHTML = `<div class="error">加载出错：${error.message}</div>`;
    }
}

// 插件导入功能
function uploadPlugins() {
    // 创建文件输入元素
    const fileInput = document.createElement('input');
    fileInput.type = 'file';
    fileInput.accept = '.js'; // 只允许上传 js 文件
    fileInput.style.display = 'none';

    // 监听文件选择事件
    fileInput.onchange = async function(event) {
        const file = event.target.files[0];
        if (!file) return;

        // 验证文件类型
        if (!file.name.endsWith('.js')) {
            alert('只允许上传 .js 格式的文件');
            return;
        }

        // 创建 FormData 对象
        const formData = new FormData();
        formData.append('file', file);

        try {
            // 上传文件
            const response = await fetch('/api/js-plugins/upload', {
                method: 'POST',
                body: formData
            });

            const data = await response.json();

            if (data.success) {
                alert('插件导入成功');
                // 自动刷新插件列表
                await loadPlugins();
            } else {
                alert(`插件导入失败：${data.error}`);
            }
        } catch (error) {
            alert(`插件导入出错：${error.message}`);
        }
    };

    // 触发文件选择对话框
    document.body.appendChild(fileInput);
    fileInput.click();
    document.body.removeChild(fileInput);
}

// 显示插件列表
function displayPlugins(plugins) {
    const container = document.getElementById('plugins-container');

    if (!plugins || plugins.length === 0) {
        container.innerHTML = '<div class="empty">没有找到插件</div>';
        return;
    }

    const html = plugins.map(plugin => `
        <div class="plugin-item">
            <div class="plugin-info">
                <div class="plugin-name">${plugin.name}</div>
                <div class="plugin-details">
                    <span class="plugin-status ${plugin.enabled ? 'status-enabled' : 'status-disabled'}">
                        ${plugin.enabled ? '已启用' : '已禁用'}
                    </span>
                    ${plugin.error ? ` | 错误：${plugin.error}` : ''}
                </div>
            </div>
            <div class="plugin-actions">
                ${plugin.enabled ?
            `<button class="action-btn disable-btn" onclick="togglePlugin('${plugin.name}', false)">
                <span class="material-icons">block</span>
                <span>禁用</span>
            </button>` :
            `<button class="action-btn enable-btn" onclick="togglePlugin('${plugin.name}', true)">
                <span class="material-icons">check_circle</span>
                <span>启用</span>
            </button>
            <button class="action-btn uninstall-btn" onclick="uninstallPlugin('${plugin.name}')">
                <span class="material-icons">delete</span>
                <span>卸载</span>
            </button>`
        }
            </div>
        </div>
    `).join('');

    container.innerHTML = `<div class="plugin-list">${html}</div>`;
}

// 启用/禁用插件
async function togglePlugin(pluginName, enable) {
    try {
        const url = enable ?
            `/api/js-plugins/${pluginName}/enable` :
            `/api/js-plugins/${pluginName}/disable`;

        const response = await fetch(url, {
            method: 'PUT'
        });
        const data = await response.json();

        if (data.success) {
            // 操作成功，重新加载插件列表
            await loadPlugins();
        } else {
            alert(`${enable ? '启用' : '禁用'}插件失败：${data.error}`);
        }
    } catch (error) {
        alert(`${enable ? '启用' : '禁用'}插件出错：${error.message}`);
    }
}

// 卸载插件功能
async function uninstallPlugin(pluginName) {
    if (!confirm(`确定要卸载插件 "${pluginName}" 吗？此操作不可恢复。`)) {
        return;
    }

    try {
        const response = await fetch(`/api/js-plugins/${pluginName}/uninstall`, {
            method: 'DELETE'
        });
        const data = await response.json();

        if (data.success) {
            alert('插件卸载成功');
            // 重新加载插件列表
            await loadPlugins();
        } else {
            alert(`插件卸载失败：${data.error}`);
        }
    } catch (error) {
        alert(`插件卸载出错：${error.message}`);
    }
}

/*============================后台类型配置函数=================================*/
async function loadBackConfInfo() {
    try {
        const response = await fetch('/api/back-conf/load');
        const data = await response.json();
        if (data.success) {
            displayBackConfInfo(data.data);
        }
    } catch (error) {
        console.error('加载后台配置失败:', error);
    }
}

function displayBackConfInfo(config) {
    const container = document.getElementById('backend-options');
    const apiOptions = config.api_options || [];
    const currentType = config.api_type || 1;
    // 保存当前类型到全局变量
    window.currentBackendType = currentType;
    window.selectedBackendType = currentType;

    const html = apiOptions.map(opt => `
        <div class="backend-option ${opt.type === currentType ? 'selected' : ''}"
             data-type="${opt.type}" onclick="selectBackendType(${opt.type})">
            <div class="backend-option-title">
                <span class="radio-circle"></span>
                ${opt.name}
            </div>
            <div class="backend-option-desc">
                ${opt.type === 1 ? '使用 MusicFree 插件搜索音乐' : '使用 LXServer 接口搜索音乐'}
            </div>
        </div>
    `).join('');

    container.innerHTML = html;

    // 根据当前选择显示/隐藏配置区域，并加载对应数据
    updateConfigAreas(currentType);
}

function selectBackendType(apiType) {
    const currentType = window.currentBackendType;

    if (parseInt(apiType) === currentType) {
        return;
    }

    if (!confirm('确定要切换接口生态吗？')) {
        return;
    }

    window.selectedBackendType = apiType;
    saveBackendType();
}

async function saveBackendType() {
    const newType = window.selectedBackendType;
    const currentType = window.currentBackendType;

    try {
        const response = await fetch('/api/back-conf/update', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ api_type: newType })
        });
        const data = await response.json();
        if (data.success) {
            // 更新全局变量
            window.currentBackendType = newType;
            alert('切换成功');
            // 根据新类型更新配置区域
            updateConfigAreas(newType);
            // 更新选项卡选中状态
            document.querySelectorAll('.backend-option').forEach(el => {
                el.classList.remove('selected');
                if (parseInt(el.dataset.type) === newType) {
                    el.classList.add('selected');
                }
            });
            // 加载对应类型的数据
            if (newType === 1) {
                loadPlugins();
                await loadPluginSource();
            } else {
                await loadLxServerConfig();
            }
        } else {
            alert(`保存失败：${data.error}`);
        }
    } catch (error) {
        alert(`保存出错：${error.message}`);
    }
}

function updateConfigAreas(apiType) {
    const pluginArea = document.getElementById('plugin-config-area');
    const lxserverArea = document.getElementById('lxserver-config-area');

    // 获取需要控制显示的按钮
    const pluginUploadBtn = document.getElementById('plugin-upload-btn');
    const pluginOnlineBtn = document.getElementById('plugin-online-btn');
    const pluginRefreshBtn = document.getElementById('plugin-refresh-btn');
    const pluginChannelBtn = document.getElementById('plugin-channel-btn');
    const lxserverProjectBtn = document.getElementById('lxserver-project-btn');

    if (apiType === 1) {
        // MusicFree 模式：显示插件相关按钮，隐藏 LX Server 按钮
        pluginArea.style.display = 'block';
        lxserverArea.style.display = 'none';

        pluginUploadBtn.style.display = 'inline-flex';
        pluginOnlineBtn.style.display = 'inline-flex';
        pluginRefreshBtn.style.display = 'inline-flex';
        pluginChannelBtn.style.display = 'inline-flex';
        lxserverProjectBtn.style.display = 'none';
    } else {
        // LXServer 模式：显示 LX Server 按钮，隐藏插件相关按钮
        pluginArea.style.display = 'none';
        lxserverArea.style.display = 'block';

        pluginUploadBtn.style.display = 'none';
        pluginOnlineBtn.style.display = 'none';
        pluginRefreshBtn.style.display = 'none';
        pluginChannelBtn.style.display = 'none';
        lxserverProjectBtn.style.display = 'inline-flex';
    }
}

/*============================高级配置函数=================================*/
let boxPlayPlatform = 'all';
let availablePlatforms = {};

async function loadAdvancedConfig() {
    try {
        const [advancedRes, platformRes] = await Promise.all([
            fetch('/api/advanced-config/load'),
            fetch('/api/box-play-platform/load')
        ]);

        const advancedData = await advancedRes.json();
        const platformData = await platformRes.json();

        if (advancedData.success) {
            displayAdvancedConfig(advancedData.data);
        }

        if (platformData.success) {
            boxPlayPlatform = platformData.data.platform || 'all';
            availablePlatforms = platformData.data.platforms || {};
            displayBoxPlayPlatform(availablePlatforms, boxPlayPlatform);
        }
    } catch (error) {
        console.error('加载高级配置失败:', error);
    }
}

function displayBoxPlayPlatform(platforms, currentPlatform) {
    const platformCard = document.getElementById('boxPlayPlatformCard');
    const platformSelect = document.getElementById('boxPlayPlatformSelect');

    const entries = Object.entries(platforms);

    if (entries.length === 0) {
        platformCard.style.display = 'none';
        return;
    }

    platformCard.style.display = 'block';

    let options = '<option value="all">聚合搜索</option>';
    entries.forEach(([key, name]) => {
        const selected = key === currentPlatform ? 'selected' : '';
        options += `<option value="${key}" ${selected}>${name}</option>`;
    });
    platformSelect.innerHTML = options;
}

function displayAdvancedConfig(config) {
    const autoConvertRow = document.getElementById('autoConvertRow');
    if (window.currentBackendType === 2) {
        autoConvertRow.style.display = 'flex';
    } else {
        autoConvertRow.style.display = 'none';
    }

    document.getElementById('autoAddSongCheckbox').checked = config.auto_add_song || false;
    document.getElementById('autoConvertCheckbox').checked = config.auto_convert || false;

    const aiapiInfo = config.aiapi_info || {};
    document.getElementById('aiApiEnabledCheckbox').checked = aiapiInfo.enabled || false;
    document.getElementById('aiBaseUrlInput').value = aiapiInfo.base_url || '';
    document.getElementById('aiApiKeyInput').value = aiapiInfo.api_key || '';
    document.getElementById('aiModelInput').value = aiapiInfo.model || 'qwen-plus';
}

async function saveAdvancedConfig() {
    const autoAddSong = document.getElementById('autoAddSongCheckbox').checked;
    const autoConvert = window.currentBackendType === 2 ? document.getElementById('autoConvertCheckbox').checked : false;
    const aiApiEnabled = document.getElementById('aiApiEnabledCheckbox').checked;
    const aiBaseUrl = document.getElementById('aiBaseUrlInput').value;
    const aiApiKey = document.getElementById('aiApiKeyInput').value;
    const aiModel = document.getElementById('aiModelInput').value;

    const aiapi_info = {
        enabled: aiApiEnabled,
        base_url: aiBaseUrl,
        api_key: aiApiKey,
        model: aiModel
    };

    const payload = {
        auto_add_song: autoAddSong,
        aiapi_info: aiapi_info
    };

    if (window.currentBackendType === 2) {
        payload.auto_convert = autoConvert;
    }

    try {
        const [advancedRes, platformRes] = await Promise.all([
            fetch('/api/advanced-config/update', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            }),
            fetch('/api/box-play-platform/update', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ platform: document.getElementById('boxPlayPlatformSelect').value })
            })
        ]);

        const advancedData = await advancedRes.json();
        const platformData = await platformRes.json();

        if (advancedData.success && platformData.success) {
            alert('保存成功');
            closeAdvancedConfig();
        } else {
            const error = advancedData.error || platformData.error || '未知错误';
            alert('保存失败: ' + error);
        }
    } catch (error) {
        alert('保存失败: ' + error.message);
    }
}

function openAdvancedConfig() {
    loadAdvancedConfig();
    const modal = document.getElementById('advancedConfigModal');
    modal.classList.add('show');
}

function closeAdvancedConfig() {
    const modal = document.getElementById('advancedConfigModal');
    modal.classList.remove('show');
}

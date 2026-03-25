// ============ 字体加载检测 ============
// 检测字体加载完成，避免图标文字闪烁
(function () {
  // 使用 Promise.race 实现超时保护
  const fontLoadTimeout = new Promise((resolve) => {
    setTimeout(() => {
      console.warn("字体加载超时，强制显示图标");
      resolve("timeout");
    }, 3000);
  });

  const fontLoadReady = document.fonts.ready.then(() => "loaded");

  Promise.race([fontLoadReady, fontLoadTimeout])
    .then((result) => {
      document.body.classList.add("fonts-loaded");
      if (result === "loaded") {
        console.log("Material Icons 字体加载完成");
      }
    })
    .catch((error) => {
      console.error("字体加载检测失败:", error);
      // 出错时也显示图标，避免永久隐藏
      document.body.classList.add("fonts-loaded");
    });
})();

// $(function () {

// })

// ============ 无障碍辅助函数 ============

// 屏幕阅读器状态通知函数
function announceToScreenReader(message) {
  const announcer = document.getElementById("sr-announcer");
  if (announcer) {
    announcer.textContent = "";
    setTimeout(() => {
      announcer.textContent = message;
    }, 100);
  }
}

// 批量填充 select 选项（优化读屏性能）
function fillSelectOptions(
  selectElement,
  options,
  selectedValue,
  announceMessage,
) {
  const $select = $(selectElement);

  // 设置忙碌状态，告知读屏软件正在加载
  $select.attr("aria-busy", "true");

  // 构建所有 option 的 HTML 字符串
  const optionsHtml = options
    .map((opt) => {
      const isSelected = opt.value === selectedValue;
      const selectedAttr = isSelected ? " selected" : "";
      // 转义 HTML 特殊字符
      const escapedText = $("<div>").text(opt.text).html();
      const escapedValue = $("<div>").text(opt.value).html();
      return `<option value="${escapedValue}"${selectedAttr}>${escapedText}</option>`;
    })
    .join("");

  // 一次性设置所有选项
  $select.html(optionsHtml);

  // 恢复状态
  $select.attr("aria-busy", "false");

  // 通知读屏软件加载完成
  if (announceMessage) {
    announceToScreenReader(announceMessage);
  }
}

// 弹窗焦点管理
let lastFocusedElement = null;
const openDialogs = new Set();

function openDialog(dialogId) {
  const dialog = document.getElementById(dialogId);
  if (!dialog) return;

  // 保存当前焦点元素
  lastFocusedElement = document.activeElement;

  // 显示遮罩层
  const overlay = document.getElementById("component-overlay");
  if (overlay) {
    overlay.style.display = "block";
    setTimeout(() => overlay.classList.add("show"), 10);
  }

  // 显示弹窗
  dialog.style.display = "block";
  setTimeout(() => dialog.classList.add("show"), 10);
  openDialogs.add(dialogId);

  // 将焦点移到弹窗内第一个可交互元素
  setTimeout(() => {
    const firstFocusable = dialog.querySelectorAll(
      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
    )[0];
    if (firstFocusable) {
      firstFocusable.focus();
    }
  }, 100);
}

function closeDialog(dialogId) {
  const dialog = document.getElementById(dialogId);
  if (!dialog) return;

  // 隐藏弹窗动画
  dialog.classList.remove("show");
  openDialogs.delete(dialogId);

  // 如果没有其他打开的弹窗，隐藏遮罩层
  if (openDialogs.size === 0) {
    const overlay = document.getElementById("component-overlay");
    if (overlay) {
      overlay.classList.remove("show");
      setTimeout(() => (overlay.style.display = "none"), 300);
    }
  }

  // 延迟隐藏弹窗以显示动画
  setTimeout(() => {
    dialog.style.display = "none";
  }, 300);

  // 恢复焦点到触发按钮
  if (lastFocusedElement) {
    lastFocusedElement.focus();
    lastFocusedElement = null;
  }
}

// 关闭所有弹窗
function closeAllDialogs() {
  const dialogs = Array.from(openDialogs);
  dialogs.forEach((dialogId) => closeDialog(dialogId));
}

// 更新进度条 ARIA 属性
function updateProgressAria(currentTime, totalTime) {
  const progress = document.getElementById("progress");
  if (progress) {
    const percentage =
      totalTime > 0 ? Math.round((currentTime / totalTime) * 100) : 0;
    progress.setAttribute("aria-valuenow", percentage);

    const currentMin = Math.floor(currentTime / 60);
    const currentSec = Math.floor(currentTime % 60);
    const totalMin = Math.floor(totalTime / 60);
    const totalSec = Math.floor(totalTime % 60);
    progress.setAttribute(
      "aria-valuetext",
      `已播放 ${currentMin} 分 ${currentSec} 秒，共 ${totalMin} 分 ${totalSec} 秒`,
    );
  }
}

// 更新音量滑块 ARIA 属性
function updateVolumeAria(volume) {
  const volumeSlider = document.getElementById("volume");
  if (volumeSlider) {
    volumeSlider.setAttribute("aria-valuenow", volume);
  }
}

// 更新收藏按钮 ARIA 属性
function updateFavoriteAria(isFavorited) {
  const favoriteBtn = document.querySelector(".favorite");
  if (favoriteBtn) {
    favoriteBtn.setAttribute(
      "aria-label",
      isFavorited ? "取消收藏" : "收藏歌曲",
    );
  }
}

// 更新语音口令开关 ARIA 属性
function updatePullAskAria(isEnabled) {
  const toggle = document.getElementById("pullAskToggle");
  if (toggle) {
    toggle.setAttribute("aria-checked", isEnabled ? "true" : "false");
  }
}

// ============ 原有代码 ============

let isPlaying = false;
let playModeIndex = 2;
//重新设计playModes
const playModes = {
  0: {
    icon: "repeat_one",
    cmd: "单曲循环",
  },
  1: {
    icon: "repeat",
    cmd: "全部循环",
  },
  2: {
    icon: "shuffle",
    cmd: "随机播放",
  },
  3: {
    icon: "filter_1",
    cmd: "单曲播放",
  },
  4: {
    icon: "playlist_play",
    cmd: "顺序播放",
  },
};

let favoritelist = []; //收藏列表

// ============ 本机播放器状态管理 ============

// 本机播放器状态管理对象
const WebPlayer = {
  // 获取当前播放列表名称
  getPlaylist: function () {
    return localStorage.getItem("web_playlist") || "全部";
  },

  // 设置当前播放列表
  setPlaylist: function (playlist) {
    localStorage.setItem("web_playlist", playlist);
  },

  // 获取当前播放歌曲
  getCurrentMusic: function () {
    return localStorage.getItem("web_current_music") || "";
  },

  // 设置当前播放歌曲
  setCurrentMusic: function (music) {
    localStorage.setItem("web_current_music", music);
  },

  // 获取播放模式
  getPlayMode: function () {
    const mode = localStorage.getItem("web_play_mode");
    return mode !== null ? parseInt(mode) : 2; // 默认随机播放
  },

  // 设置播放模式
  setPlayMode: function (mode) {
    localStorage.setItem("web_play_mode", mode.toString());
  },

  // 获取播放列表数组
  getPlayList: function () {
    const list = localStorage.getItem("web_play_list");
    return list ? JSON.parse(list) : [];
  },

  // 设置播放列表数组
  setPlayList: function (list) {
    localStorage.setItem("web_play_list", JSON.stringify(list));
  },

  // 获取当前播放索引
  getCurrentIndex: function () {
    const index = localStorage.getItem("web_current_index");
    return index !== null ? parseInt(index) : -1;
  },

  // 设置当前播放索引
  setCurrentIndex: function (index) {
    localStorage.setItem("web_current_index", index.toString());
  },

  // 获取音量
  getVolume: function () {
    const volume = localStorage.getItem("web_volume");
    return volume !== null ? parseInt(volume) : 50;
  },

  // 设置音量
  setVolume: function (volume) {
    localStorage.setItem("web_volume", volume.toString());
  },

  // 检查是否已收藏（直接使用全局 favoritelist，数据来源于服务器）
  isFavorited: function (music) {
    return favoritelist.includes(music);
  },
};

// 本机播放：加载并播放指定歌曲
function loadAndPlayMusic(musicName) {
  console.log("loadAndPlayMusic:", musicName);

  $.get(`/musicinfo?name=${musicName}`, function (data, status) {
    console.log(data);
    if (data.ret == "OK") {
      const audioElement = document.getElementById("audio");

      // 设置音频源
      audioElement.src = data.url;

      // 播放音频
      audioElement
        .play()
        .then(() => {
          console.log("播放成功:", musicName);

          // 更新本机播放状态
          WebPlayer.setCurrentMusic(musicName);

          // 更新播放列表和索引
          const playlist = $("#music_list").val();
          WebPlayer.setPlaylist(playlist);

          const playList = WebPlayer.getPlayList();
          const index = playList.indexOf(musicName);
          if (index !== -1) {
            WebPlayer.setCurrentIndex(index);
          }

          // 更新 UI
          updateWebPlayingUI();

          // 更新收藏按钮状态
          updateWebFavoriteButton();
        })
        .catch((error) => {
          console.error("播放失败:", error);
          alert("播放失败: " + error.message);
        });
    }
  });
}

function webPlay() {
  console.log("webPlay");
  const music_name = $("#music_name").val();

  if (!music_name) {
    alert("请选择要播放的歌曲");
    return;
  }

  // 获取当前播放列表
  const playlist = $("#music_list").val();
  const playlistData = $("#music_name option")
    .map(function () {
      return $(this).val();
    })
    .get();

  // 保存播放列表到 localStorage
  WebPlayer.setPlayList(playlistData);
  WebPlayer.setPlaylist(playlist);

  // 加载并播放歌曲
  loadAndPlayMusic(music_name);
}

function play() {
  var did = $("#did").val();
  if (did == "web_device") {
    webPlay();
  } else {
    playOnDevice();
  }
}

function playOnDevice() {
  console.log("playOnDevice");
  var music_list = $("#music_list").val();
  var music_name = $("#music_name").val();
  if (no_warning) {
    do_play_music_list(music_list, music_name);
    return;
  }
  $.get(`/musicinfo?name=${music_name}`, function (data, status) {
    console.log(data);
    if (data.ret == "OK") {
      console.log(
        "%cmd.js:42 validHost(data.url) ",
        "color: #007acc;",
        validHost(data.url),
      );
      validHost(data.url) && do_play_music_list(music_list, music_name);
    }
  });
}
function stopPlay() {
  var did = $("#did").val();

  if (did == "web_device") {
    // 本机播放：停止播放
    const audioElement = document.getElementById("audio");
    audioElement.pause();
    audioElement.currentTime = 0;

    // 更新 UI
    updateWebPlayingUI();

    console.log("本机停止播放");
  } else {
    // 设备播放：调用后端接口
    $.ajax({
      type: "POST",
      url: "/device/stop",
      contentType: "application/json; charset=utf-8",
      data: JSON.stringify({
        did: did,
      }),
      success: () => {
        console.log("stop play succ");
      },
      error: () => {
        console.log("stop play failed");
      },
    });
  }
}

function prevTrack() {
  var did = $("#did").val();

  if (did == "web_device") {
    // 本机播放：播放上一首
    webPlayPrevious();
  } else {
    // 设备播放：发送命令
    sendcmd("上一首");
  }
}

function nextTrack() {
  var did = $("#did").val();

  if (did == "web_device") {
    // 本机播放：播放下一首
    webPlayNext();
  } else {
    // 设备播放：发送命令
    sendcmd("下一首");
  }
}

// 本机播放：播放上一首
function webPlayPrevious() {
  const playList = WebPlayer.getPlayList();
  const currentIndex = WebPlayer.getCurrentIndex();

  if (playList.length === 0) {
    alert("播放列表为空");
    return;
  }

  let prevIndex;
  const playMode = WebPlayer.getPlayMode();

  if (playMode === 2) {
    // 随机播放：随机选择一首（不包括当前）
    const availableIndices = playList
      .map((_, i) => i)
      .filter((i) => i !== currentIndex);
    if (availableIndices.length > 0) {
      prevIndex =
        availableIndices[Math.floor(Math.random() * availableIndices.length)];
    } else {
      prevIndex = 0;
    }
  } else {
    // 其他模式：播放前一首
    prevIndex = currentIndex - 1;
    if (prevIndex < 0) {
      prevIndex = playList.length - 1;
    }
  }

  const prevMusic = playList[prevIndex];
  if (prevMusic) {
    loadAndPlayMusic(prevMusic);
  }
}

// 本机播放：播放下一首
function webPlayNext() {
  const playList = WebPlayer.getPlayList();
  const currentIndex = WebPlayer.getCurrentIndex();

  if (playList.length === 0) {
    alert("播放列表为空");
    return;
  }

  let nextIndex;
  const playMode = WebPlayer.getPlayMode();

  switch (playMode) {
    case 0: // 单曲循环
      nextIndex = currentIndex;
      break;

    case 1: // 全部循环
      nextIndex = (currentIndex + 1) % playList.length;
      break;

    case 2: // 随机播放
      const availableIndices = playList
        .map((_, i) => i)
        .filter((i) => i !== currentIndex);
      if (availableIndices.length > 0) {
        nextIndex =
          availableIndices[Math.floor(Math.random() * availableIndices.length)];
      } else {
        nextIndex = Math.floor(Math.random() * playList.length);
      }
      break;

    case 3: // 单曲播放
      // 不自动播放下一首
      return;

    case 4: // 顺序播放
      nextIndex = currentIndex + 1;
      if (nextIndex >= playList.length) {
        // 到末尾停止
        return;
      }
      break;

    default:
      nextIndex = (currentIndex + 1) % playList.length;
  }

  const nextMusic = playList[nextIndex];
  if (nextMusic) {
    loadAndPlayMusic(nextMusic);
  }
}

function togglePlayMode(isSend = true) {
  var did = $("#did").val();
  const modeBtnIcon = $("#modeBtn .material-icons");

  if (did == "web_device") {
    // 本机播放：使用 localStorage 管理播放模式
    let currentMode = WebPlayer.getPlayMode();

    // 切换到下一个模式
    const nextMode = (currentMode + 1) % Object.keys(playModes).length;
    WebPlayer.setPlayMode(nextMode);

    // 更新图标和提示（显示新的模式）
    modeBtnIcon.text(playModes[nextMode].icon);
    $("#modeBtn .tooltip").text(playModes[nextMode].cmd);

    console.log(`播放模式已切换为: ${nextMode} ${playModes[nextMode].cmd}`);

    // 更新 audio 元素的 loop 属性
    const audioElement = document.getElementById("audio");
    if (nextMode === 0) {
      // 单曲循环
      audioElement.loop = true;
    } else {
      audioElement.loop = false;
    }

    announceToScreenReader(`播放模式已切换为${playModes[nextMode].cmd}`);
  } else {
    // 设备播放：使用原有逻辑
    if (playModeIndex === "") {
      playModeIndex = 2;
    }
    modeBtnIcon.text(playModes[playModeIndex].icon);
    $("#modeBtn .tooltip").text(playModes[playModeIndex].cmd);

    isSend && sendcmd(playModes[playModeIndex].cmd);
    console.log(
      `当前播放模式: ${playModeIndex} ${playModes[playModeIndex].cmd}`,
    );
    playModeIndex = (playModeIndex + 1) % Object.keys(playModes).length;
  }
}

// 调用后端接口将歌曲加入指定歌单
function playlistAddMusic(playlistName, musicName) {
  return $.ajax({
    type: "POST",
    url: "/playlistaddmusic",
    contentType: "application/json; charset=utf-8",
    data: JSON.stringify({ name: playlistName, music_list: [musicName] }),
  });
}

// 调用后端接口将歌曲从指定歌单移除
function playlistDelMusic(playlistName, musicName) {
  return $.ajax({
    type: "POST",
    url: "/playlistdelmusic",
    contentType: "application/json; charset=utf-8",
    data: JSON.stringify({ name: playlistName, music_list: [musicName] }),
  });
}

function addToFavorites() {
  const isLiked = $(".favorite").hasClass("favorite-active");
  const musicName = WebPlayer.getCurrentMusic() || $("#music_name").val();

  if (!musicName) {
    alert("请先选择或播放一首歌曲");
    return;
  }

  if (isLiked) {
    $(".favorite").removeClass("favorite-active");
    favoritelist = favoritelist.filter((item) => item !== musicName);
    updateFavoriteAria(false);
    announceToScreenReader(`已取消收藏 ${musicName}`);
    playlistDelMusic("收藏", musicName)
      .done((data) => {
        console.log("取消收藏成功:", musicName, data);
      })
      .fail(() => {
        console.error("取消收藏失败:", musicName);
      });
  } else {
    $(".favorite").addClass("favorite-active");
    favoritelist.push(musicName);
    updateFavoriteAria(true);
    announceToScreenReader(`已收藏 ${musicName}`);
    playlistAddMusic("收藏", musicName)
      .done((data) => {
        console.log("收藏成功:", musicName, data);
      })
      .fail(() => {
        console.error("收藏失败:", musicName);
      });
  }
}

function openSettings() {
  console.log("打开设置");
  window.location.href = "setting.html";
}
function toggleVolume() {
  const isVisible = $("#volume-component").is(":visible");
  if (isVisible) {
    closeDialog("volume-component");
  } else {
    openDialog("volume-component");
  }
}

function toggleSearch() {
  const isVisible = $("#search-component").is(":visible");
  if (isVisible) {
    closeDialog("search-component");
  } else {
    openDialog("search-component");
  }
}

function toggleTimer() {
  const isVisible = $("#timer-component").is(":visible");
  if (isVisible) {
    closeDialog("timer-component");
  } else {
    openDialog("timer-component");
  }
}

function togglePlayLink() {
  const isVisible = $("#playlink-component").is(":visible");
  if (isVisible) {
    closeDialog("playlink-component");
  } else {
    openDialog("playlink-component");
  }
}

function toggleLocalPlay() {
  $("#audio").fadeIn();
}

function toggleWarning() {
  const isVisible = $("#warning-component").is(":visible");
  if (isVisible) {
    closeDialog("warning-component");
  } else {
    openDialog("warning-component");
  }
}

function toggleDelete() {
  var del_music_name = $("#music_name").val();
  $("#delete-music-name").text(del_music_name);
  const isVisible = $("#delete-component").is(":visible");
  if (isVisible) {
    closeDialog("delete-component");
  } else {
    openDialog("delete-component");
  }
}
function confirmDelete() {
  var del_music_name = $("#music_name").val();
  console.log(`删除歌曲 ${del_music_name}`);
  $("#delete-component").hide(); // 隐藏删除框
  $.ajax({
    type: "POST",
    url: "/delmusic",
    data: JSON.stringify({ name: del_music_name }),
    contentType: "application/json; charset=utf-8",
    success: () => {
      alert(`删除 ${del_music_name} 成功`);
      refresh_music_list();
    },
    error: () => {
      alert(`删除 ${del_music_name} 失败`);
    },
  });
}
function formatTime(seconds) {
  // 处理无效值
  if (!isFinite(seconds) || isNaN(seconds) || seconds < 0) {
    return "0:00";
  }

  const minutes = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${minutes}:${secs < 10 ? "0" : ""}${secs}`; // Format time as mm:ss
}

var offset = 0;
var duration = 0;
let no_warning = localStorage.getItem("no-warning");

// 全局 did 变量初始化，默认为本机播放
var did = localStorage.getItem("cur_did") || "web_device";

// 拉取现有配置
$.get("/getsetting", function (data, status) {
  console.log(data, status);
  localStorage.setItem("mi_did", data.mi_did);

  did = localStorage.getItem("cur_did") || "web_device";
  var dids = [];
  if (data.mi_did != null) {
    dids = data.mi_did.split(",");
  }
  console.log("cur_did", did);
  console.log("dids", dids);

  // 如果当前 did 不是 web_device，且配置了设备列表，但 did 不在列表中，则使用第一个设备
  if (did != "web_device" && dids.length > 0 && !dids.includes(did)) {
    did = dids[0];
    localStorage.setItem("cur_did", did);
  }

  // 如果 did 仍然为空或未设置，默认使用 web_device
  if (!did || did === "") {
    did = "web_device";
    localStorage.setItem("cur_did", did);
  }

  window.did = did;
  $.get(`/getvolume?did=${did}`, function (data, status) {
    console.log(data, status, data["volume"]);
    $("#volume").val(data.volume);
  });
  refresh_music_list();

  $("#did").empty();
  var dids = data.mi_did.split(",");

  // 收集所有设备选项
  var deviceOptions = [];
  $.each(dids, function (index, value) {
    var cur_device = Object.values(data.devices).find(
      (device) => device.did === value,
    );
    if (cur_device) {
      deviceOptions.push({
        value: value,
        text: cur_device.name,
      });

      if (value === did) {
        playModeIndex = cur_device.play_type;
        console.log(
          "%c当前设备播放模式: ",
          "color: #007acc;",
          cur_device.play_type,
        );
        togglePlayMode(false);
      }
    }
  });

  // 添加本机选项
  deviceOptions.push({
    value: "web_device",
    text: "本机",
  });

  // 批量填充设备选项
  fillSelectOptions(
    "#did",
    deviceOptions,
    did,
    `设备列表已加载，共 ${deviceOptions.length} 个设备`,
  );

  console.log("cur_did", did);
  $("#did").change(function () {
    did = $(this).val();
    localStorage.setItem("cur_did", did);
    window.did = did;
    console.log("cur_did", did);
    location.reload();
  });

  if (did == "web_device") {
    // 本机播放：显示 audio 控件和进度条
    $("#audio").fadeIn();
    $("#device-audio").fadeIn(); // 保持显示，因为进度条在这里

    // 本机播放：禁用设备相关按钮，启用本机按钮
    // 搜索、定时、测试按钮禁用
    $(".icon-item").each(function () {
      const text = $(this).find("p").text();
      if (text === "搜索" || text === "定时" || text === "测试") {
        $(this).addClass("disabled");
        $(this).css("opacity", "0.5");
        $(this).css("pointer-events", "none");
      }
    });

    // 其他按钮启用（播放模式、上一曲、播放、下一曲、停止、收藏、音量、设置）
    $("#modeBtn").removeClass("disabled");
    $(".favorite").removeClass("disabled");
  } else {
    // 设备播放：隐藏 audio 控件，显示进度条
    $("#audio").fadeOut();
    $("#device-audio").fadeIn();

    // 设备播放：恢复所有按钮
    $(".device-enable").removeClass("disabled");
    $(".icon-item").removeClass("disabled");
    $(".icon-item").css("opacity", "");
    $(".icon-item").css("pointer-events", "");
  }

  // 初始化对话记录开关状态
  updatePullAskUI(data.enable_pull_ask);
});

function compareVersion(version1, version2) {
  const v1 = version1.split(".").map(Number);
  const v2 = version2.split(".").map(Number);
  const len = Math.max(v1.length, v2.length);

  for (let i = 0; i < len; i++) {
    const num1 = v1[i] || 0;
    const num2 = v2[i] || 0;
    if (num1 > num2) return 1;
    if (num1 < num2) return -1;
  }
  return 0;
}

// 拉取版本
$.get("/getversion", function (data, status) {
  console.log(data, status, data["version"]);
  $("#version").text(`${data.version}`);

  $.get("/latestversion", function (ret, status) {
    console.log(ret, status);
    if (ret.ret == "OK") {
      const result = compareVersion(ret.version, data.version);
      if (result > 0) {
        console.log(`${ret.version} is greater than ${data.version}`);
        $("#versionnew").text("new").css("display", "inline-block");
      }
    }
  });
});

function _refresh_music_list(callback) {
  $("#music_list").empty();
  $.get("/musiclist", function (data, status) {
    console.log(data, status);
    favoritelist = data["收藏"] || [];

    // 收集所有播放列表选项
    var playlistOptions = [];
    $.each(data, function (key, value) {
      let cnt = value.length;
      playlistOptions.push({
        value: key,
        text: `${key} (${cnt})`,
      });
    });

    // 批量填充播放列表选项
    fillSelectOptions(
      "#music_list",
      playlistOptions,
      null, // 选中值将在后面通过 trigger('change') 设置
      `播放列表已加载，共 ${playlistOptions.length} 个列表`,
    );

    $("#music_list").change(function () {
      const selectedValue = $(this).val();
      localStorage.setItem("cur_playlist", selectedValue);
      $("#music_name").empty();
      const cur_music = localStorage.getItem("cur_music");
      console.log("#music_name cur_music", cur_music);

      // 收集所有歌曲选项
      var songOptions = [];
      $.each(data[selectedValue], function (index, item) {
        songOptions.push({
          value: item,
          text: item,
        });
      });

      // 批量填充歌曲选项
      fillSelectOptions(
        "#music_name",
        songOptions,
        cur_music,
        `歌曲列表已加载，共 ${songOptions.length} 首歌曲`,
      );

      // 本机播放：更新播放列表
      var did = $("#did").val();
      if (did == "web_device") {
        const playlistData = $("#music_name option")
          .map(function () {
            return $(this).val();
          })
          .get();
        WebPlayer.setPlayList(playlistData);
        WebPlayer.setPlaylist(selectedValue);
        console.log("本机播放列表已更新:", selectedValue);
      }
    });

    // 监听歌曲选择变化（本机播放）
    $("#music_name").on("change", function () {
      var did = $("#did").val();
      if (did == "web_device") {
        const selectedMusic = $(this).val();
        // 保存用户选择的歌曲（不自动播放）
        if (selectedMusic) {
          WebPlayer.setCurrentMusic(selectedMusic);
          console.log("本机选择歌曲已保存:", selectedMusic);
        }
      }
    });

    // 本机模式：直接使用 WebPlayer 的状态，不调用后端接口
    if (did == "web_device") {
      const savedPlaylist = WebPlayer.getPlaylist();
      const savedMusic = WebPlayer.getCurrentMusic();

      console.log(
        "恢复本机播放状态 - 歌单:",
        savedPlaylist,
        "歌曲:",
        savedMusic,
      );

      // 恢复歌单选择
      if (savedPlaylist && data.hasOwnProperty(savedPlaylist)) {
        $("#music_list").val(savedPlaylist);
        $("#music_list").trigger("change");

        // 等待歌单切换完成后，恢复歌曲选择
        setTimeout(function () {
          if (
            savedMusic &&
            $("#music_name option[value='" + savedMusic + "']").length > 0
          ) {
            $("#music_name").val(savedMusic);
            console.log("已恢复歌曲选择:", savedMusic);
          }
        }, 100);
      } else {
        // 没有保存的歌单，使用默认
        $("#music_list").trigger("change");
      }
      callback();
    } else {
      // 设备模式：使用原有逻辑
      $("#music_list").trigger("change");

      // 获取当前播放列表
      $.get(`/curplaylist?did=${did}`, function (playlist, status) {
        if (playlist != "") {
          $("#music_list").val(playlist);
          $("#music_list").trigger("change");
        } else {
          // 使用本地记录的
          playlist = localStorage.getItem("cur_playlist");
          if (data.hasOwnProperty(playlist)) {
            $("#music_list").val(playlist);
            $("#music_list").trigger("change");
          }
        }
      });
      callback();
    }
  });
}

// 拉取播放列表
function refresh_music_list() {
  // 刷新列表时清空并临时禁用搜索框
  const searchInput = document.getElementById("search");
  const oriPlaceHolder = searchInput.placeholder;
  const oriValue = searchInput.value;
  const inputEvent = new Event("input", { bubbles: true });
  searchInput.value = "";
  // 分发事件，让其他控件改变状态
  searchInput.dispatchEvent(inputEvent);
  searchInput.disabled = true;
  searchInput.placeholder = "请等待...";

  _refresh_music_list(() => {
    // 刷新完成再启用
    searchInput.disabled = false;
    searchInput.value = oriValue;
    searchInput.dispatchEvent(inputEvent);
    searchInput.placeholder = oriPlaceHolder;
    // 获取下正在播放的音乐
    if (did != "web_device") {
      connectWebSocket(did);
    }
  });
}

function do_play_music_list(listname, musicname) {
  $.ajax({
    type: "POST",
    url: "/playmusiclist",
    contentType: "application/json; charset=utf-8",
    data: JSON.stringify({
      did: did,
      listname: listname,
      musicname: musicname,
    }),
    success: () => {
      console.log("do_play_music_list succ", listname, musicname);
    },
    error: () => {
      console.log("do_play_music_list failed", listname, musicname);
    },
  });
}

$("#play_music_list").on("click", () => {
  var music_list = $("#music_list").val();
  var music_name = $("#music_name").val();
  if (no_warning) {
    do_play_music_list(music_list, music_name);
    return;
  }
  $.get(`/musicinfo?name=${music_name}`, function (data, status) {
    console.log(data);
    if (data.ret == "OK") {
      validHost(data.url) && do_play_music_list(music_list, music_name);
    }
  });
});

function playUrl() {
  var url = $("#music-url").val();
  const encoded_url = encodeURIComponent(url);
  $.get(`/playurl?url=${encoded_url}&did=${did}`, function (data, status) {
    console.log(data);
  });
}

function playProxyUrl() {
  const origin_url = $("#music-url").val();
  const protocol = window.location.protocol;
  const host = window.location.host;
  const baseUrl = `${protocol}//${host}`;
  const urlb64 = btoa(origin_url);
  const url = `${baseUrl}/proxy?urlb64=${urlb64}`;
  const encoded_url = encodeURIComponent(url);
  $.get(`/playurl?url=${encoded_url}&did=${did}`, function (data, status) {
    console.log(data);
  });
}

function playTts() {
  var value = $("#text-tts").val();
  $.get(`/playtts?text=${value}&did=${did}`, function (data, status) {
    console.log(data);
  });
}

function sendCustomCmd() {
  var cmd = $("#custom-cmd").val();
  if (!cmd || cmd.trim() === "") {
    alert("请输入自定义口令");
    return;
  }
  $.ajax({
    type: "POST",
    url: "/cmd",
    contentType: "application/json; charset=utf-8",
    data: JSON.stringify({ did: did, cmd: cmd }),
    success: () => {
      console.log("发送自定义口令成功:", cmd);
      alert(`口令 "${cmd}" 已发送`);
    },
    error: () => {
      console.log("发送自定义口令失败:", cmd);
      alert(`口令 "${cmd}" 发送失败`);
    },
  });
}

function do_play_music(musicname, searchkey) {
  $.ajax({
    type: "POST",
    url: "/playmusic",
    contentType: "application/json; charset=utf-8",
    data: JSON.stringify({
      did: did,
      musicname: musicname,
      searchkey: searchkey,
    }),
    success: () => {
      console.log("do_play_music succ", musicname, searchkey);
    },
    error: () => {
      console.log("do_play_music failed", musicname, searchkey);
    },
  });
}

// 上传功能：触发文件选择并提交到后端
function triggerUpload() {
  const uploadInput = document.getElementById("upload-file");
  if (uploadInput) {
    uploadInput.value = null;
    uploadInput.click();
  }
}

document.addEventListener("DOMContentLoaded", function () {
  const uploadInput = document.getElementById("upload-file");
  if (uploadInput) {
    uploadInput.addEventListener("change", async function (e) {
      const files = e.target.files;
      if (!files || files.length === 0) return;
      const file = files[0];
      const playlist = $("#music_list").val();
      const form = new FormData();
      form.append("playlist", playlist);
      form.append("file", file);
      try {
        const resp = await fetch("/uploadmusic", {
          method: "POST",
          body: form,
        });
        if (!resp.ok) throw new Error("网络错误");
        const data = await resp.json();
        if (data && data.ret === "OK") {
          alert("上传成功: " + data.filename);
          refresh_music_list();
        } else {
          alert("上传失败");
        }
      } catch (err) {
        console.error(err);
        alert("上传失败");
      }
    });
  }
});

$("#play").on("click", () => {
  var search_key = $("#music-name").val();
  if (search_key == null) {
    search_key = "";
  }
  var filename = $("#music-filename").val();
  if (filename == null || filename == "") {
    filename = search_key;
  }
  do_play_music(filename, search_key);
});

$("#volume").on("change", function () {
  var value = $(this).val();
  var did = $("#did").val();

  updateVolumeAria(value);

  if (did == "web_device") {
    // 本机播放：直接控制 audio 元素音量
    const audioElement = document.getElementById("audio");
    audioElement.volume = value / 100; // audio.volume 范围是 0-1

    // 保存到 localStorage
    WebPlayer.setVolume(value);

    console.log("本机音量已设置为:", value);
  } else {
    // 设备播放：调用后端接口
    $.ajax({
      type: "POST",
      url: "/setvolume",
      contentType: "application/json; charset=utf-8",
      data: JSON.stringify({ did: did, volume: value }),
      success: () => {},
      error: () => {},
    });
  }
});

function check_status_refresh_music_list(retries) {
  $.get("/cmdstatus", function (data) {
    if (data.status === "finish") {
      refresh_music_list();
    } else if (retries > 0) {
      setTimeout(function () {
        check_status_refresh_music_list(retries - 1);
      }, 1000); // 等待1秒后重试
    }
  });
}

function refreshlist() {
  $.ajax({
    type: "POST",
    url: "/api/music/refreshlist",
    contentType: "application/json; charset=utf-8",
    data: JSON.stringify({}),
    success: () => {
      check_status_refresh_music_list(3); // 最多重试3次
    },
    error: () => {
      // 请求失败时执行的操作
    },
  });
}

function sendcmd(cmd) {
  $.ajax({
    type: "POST",
    url: "/cmd",
    contentType: "application/json; charset=utf-8",
    data: JSON.stringify({ did: did, cmd: cmd }),
    success: () => {
      if (cmd == "刷新列表") {
        check_status_refresh_music_list(3); // 最多重试3次
      }
      if (
        ["全部循环", "单曲循环", "随机播放", "单曲播放", "顺序播放"].includes(
          cmd,
        )
      ) {
        location.reload();
      }
    },
    error: () => {
      // 请求失败时执行的操作
    },
  });
}

// 监听输入框的输入事件
function debounce(func, delay) {
  let timeout;
  return function (...args) {
    clearTimeout(timeout);
    timeout = setTimeout(() => func.apply(this, args), delay);
  };
}

let selectedSearchResult = null;

function handleSearch() {
  const searchInput = document.getElementById("search");
  const resultsContainer = document.getElementById("music-name");
  const musicFilenameInput = document.getElementById("music-filename");

  searchInput.addEventListener(
    "input",
    debounce(function () {
      const query = searchInput.value.trim();

      if (query.length === 0) {
        resultsContainer.innerHTML =
          '<div class="search-result-empty">请输入搜索关键词</div>';
        selectedSearchResult = null;
        musicFilenameInput.style.display = "none";
        return;
      }

      // 显示加载状态
      resultsContainer.innerHTML =
        '<div class="search-result-empty">搜索中...</div>';

      fetch(`/searchmusic?name=${encodeURIComponent(query)}`)
        .then((response) => response.json())
        .then((data) => {
          resultsContainer.innerHTML = ""; // 清空现有内容

          // 添加用户输入作为关键词选项（始终显示在第一位）
          const keywordItem = document.createElement("div");
          keywordItem.className = "search-result-item keyword-option";
          keywordItem.textContent = `🔍 使用关键词播放: ${query}`;
          keywordItem.dataset.value = query;
          keywordItem.dataset.isKeyword = "true";
          keywordItem.onclick = function () {
            selectSearchResult(this);
          };
          resultsContainer.appendChild(keywordItem);

          // 找到的歌曲结果
          if (data.length > 0) {
            data.forEach((song) => {
              const item = document.createElement("div");
              item.className = "search-result-item";
              item.textContent = song;
              item.dataset.value = song;
              item.dataset.isKeyword = "false";
              item.onclick = function () {
                selectSearchResult(this);
              };
              resultsContainer.appendChild(item);
            });
          } else {
            // 没有找到本地歌曲
            const emptyItem = document.createElement("div");
            emptyItem.className = "search-result-empty";
            emptyItem.textContent = "没有找到本地歌曲，可使用关键词在线播放";
            resultsContainer.appendChild(emptyItem);
          }

          // 默认选中关键词选项
          selectSearchResult(keywordItem);
        })
        .catch((error) => {
          console.error("Error fetching data:", error);
          resultsContainer.innerHTML =
            '<div class="search-result-empty">搜索失败，请重试</div>';
        });
    }, 600),
  );
}

function selectSearchResult(element) {
  // 移除所有选中状态
  const allItems = document.querySelectorAll(".search-result-item");
  allItems.forEach((item) => item.classList.remove("selected"));

  // 添加选中状态
  element.classList.add("selected");
  selectedSearchResult = {
    value: element.dataset.value,
    isKeyword: element.dataset.isKeyword === "true",
  };

  // 根据是否是关键词选项决定是否显示文件名输入框
  const musicFilenameInput = document.getElementById("music-filename");
  if (selectedSearchResult.isKeyword) {
    musicFilenameInput.style.display = "block";
    musicFilenameInput.placeholder = `请输入保存为的文件名称(默认: ${selectedSearchResult.value})`;
  } else {
    musicFilenameInput.style.display = "none";
  }
}

handleSearch();

function formatTime(seconds) {
  var minutes = Math.floor(seconds / 60);
  var remainingSeconds = Math.floor(seconds % 60);
  return `${minutes.toString().padStart(2, "0")}:${remainingSeconds
    .toString()
    .padStart(2, "0")}`;
}

$("audio").on("error", (e) => {
  //如果audio标签的src为空，则不做任何操作，兼容安卓端的低版本webview
  if ($("audio").attr("src") === "") {
    return;
  }
  console.log(
    "%c网页播放出现错误: ",
    "color: #007acc;",
    e.currentTarget.error.code,
    e.currentTarget.error.message,
  );
  alert(
    e.currentTarget.error.code == 4
      ? "无法打开媒体文件，XIAOMUSIC_HOSTNAME或端口地址错误，请重新设置"
      : "在线播放失败，请截图反馈: " + e.currentTarget.error.message,
  );
});
function validHost(url) {
  //如果 localStorage 中有 no-warning 则直接返回true
  if (no_warning) {
    return true;
  }
  const local = location.host;
  const host = new URL(url).host;
  // 如果当前页面的Host与设置中的XIAOMUSIC_HOSTNAME、PORT一致, 不再提醒
  if (local === host) {
    return true;
  }

  $("#local-host").text(local);
  $("#setting-host").text(host);
  $("#warning-component").show();
  console.log("%c 验证返回false", "color: #007acc;");
  return false;
}

function nowarning() {
  localStorage.setItem("no-warning", "true");
  no_warning = true;
  $("#warning-component").hide();
}
function timedShutDown(cmd) {
  $(".timer-tooltip").toggle();
  sendcmd(cmd);
  setTimeout(() => {
    $(".timer-tooltip").fadeOut();
  }, 3000);
}

function confirmSearch() {
  if (!selectedSearchResult) {
    alert("请先选择一个搜索结果");
    return;
  }

  var search_key = $("#search").val();
  var filename = selectedSearchResult.value;
  var musicfilename = $("#music-filename").val();

  // 如果是关键词选项且用户输入了自定义文件名
  if (
    selectedSearchResult.isKeyword &&
    musicfilename &&
    musicfilename.trim() !== ""
  ) {
    filename = musicfilename.trim();
  }

  console.log("confirmSearch", filename, search_key);
  do_play_music(filename, search_key);
  toggleSearch();
}

let ws = null;
let wsReconnectTimer = null;
let currentDid = null;
let isConnecting = false;

// 清理 WebSocket 连接
function cleanupWebSocket() {
  // 清除重连定时器
  if (wsReconnectTimer) {
    clearTimeout(wsReconnectTimer);
    wsReconnectTimer = null;
  }

  // 关闭现有连接
  if (ws) {
    try {
      // 移除事件监听器，避免触发 onclose 重连
      ws.onclose = null;
      ws.onerror = null;
      ws.onmessage = null;

      if (
        ws.readyState === WebSocket.OPEN ||
        ws.readyState === WebSocket.CONNECTING
      ) {
        ws.close();
      }
    } catch (e) {
      console.error("关闭 WebSocket 失败:", e);
    }
    ws = null;
  }

  isConnecting = false;
}

// 启动 WebSocket 连接
function connectWebSocket(did) {
  // 如果正在连接中，直接返回
  if (isConnecting) {
    console.log("WebSocket 正在连接中，跳过重复连接");
    return;
  }

  // 如果 did 改变了，需要重新连接
  if (currentDid !== did) {
    console.log(`设备切换: ${currentDid} -> ${did}`);
    cleanupWebSocket();
    currentDid = did;
  }

  isConnecting = true;

  fetch(`/generate_ws_token?did=${did}`)
    .then((res) => res.json())
    .then((data) => {
      const token = data.token;
      startWebSocket(did, token);
    })
    .catch((err) => {
      console.error("获取 token 失败:", err);
      isConnecting = false;
      // 5秒后重试
      wsReconnectTimer = setTimeout(() => connectWebSocket(did), 5000);
    });
}

function startWebSocket(did, token) {
  // 再次检查，确保没有重复连接
  if (
    ws &&
    (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)
  ) {
    console.log("WebSocket 已存在，跳过创建");
    isConnecting = false;
    return;
  }

  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  const wsUrl = `${protocol}://${window.location.host}/ws/playingmusic?token=${token}`;

  try {
    ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      console.log("WebSocket 连接成功");
      isConnecting = false;
    };

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.ret !== "OK") return;

      isPlaying = data.is_playing;
      let cur_music = data.cur_music || "";

      $("#playering-music").text(
        isPlaying ? `【播放中】 ${cur_music}` : `【空闲中】 ${cur_music}`,
      );

      offset = data.offset || 0;
      duration = data.duration || 0;

      if (favoritelist && favoritelist.includes(cur_music)) {
        $(".favorite").addClass("favorite-active");
      } else {
        $(".favorite").removeClass("favorite-active");
      }

      localStorage.setItem("cur_music", cur_music);
      updateProgressUI();
    };

    ws.onclose = (event) => {
      console.log("WebSocket 已断开", event.code, event.reason);
      ws = null;
      isConnecting = false;

      // 只有在非主动关闭的情况下才重连
      if (event.code !== 1000) {
        console.log("3秒后尝试重连...");
        wsReconnectTimer = setTimeout(() => connectWebSocket(did), 3000);
      }
    };

    ws.onerror = (err) => {
      console.error("WebSocket 错误:", err);
      isConnecting = false;
      // onerror 后会触发 onclose，所以这里不需要重连
    };
  } catch (e) {
    console.error("创建 WebSocket 失败:", e);
    isConnecting = false;
    wsReconnectTimer = setTimeout(() => connectWebSocket(did), 3000);
  }
}

// 每秒更新播放进度
function updateProgressUI() {
  const progressPercent = duration > 0 ? (offset / duration) * 100 : 0;
  $("#progress").val(progressPercent);
  $("#current-time").text(formatTime(offset));

  // 更新进度条 ARIA 属性
  updateProgressAria(offset, duration);
  $("#duration").text(formatTime(duration));
}

setInterval(() => {
  if (duration > 0 && isPlaying) {
    offset++;
    if (offset > duration) offset = duration;
    updateProgressUI();
  }
}, 1000);

function togglePullAsk() {
  console.log("切换对话记录状态");
  $.get("/getsetting", function (data, status) {
    const currentState = data.enable_pull_ask;
    const newState = !currentState;

    $.ajax({
      type: "POST",
      url: "/api/system/modifiysetting",
      contentType: "application/json; charset=utf-8",
      data: JSON.stringify({
        enable_pull_ask: newState,
      }),
      success: (response) => {
        console.log("对话记录状态切换成功", response);
        updatePullAskUI(newState);
        alert(newState ? "对话记录已开启" : "对话记录已关闭");
      },
      error: (error) => {
        console.error("对话记录状态切换失败", error);
        alert("切换失败，请重试");
      },
    });
  });
}

function updatePullAskUI(enabled) {
  const pullAskToggle = $("#pullAskToggle");
  if (enabled) {
    pullAskToggle.addClass("active");
  } else {
    pullAskToggle.removeClass("active");
  }
  // 更新 ARIA 属性
  updatePullAskAria(enabled);
}

// ============ 无障碍功能初始化 ============

// 键盘事件监听
$(document).on("keydown", function (e) {
  // 如果焦点在输入框、文本域或选择框中，不处理快捷键
  const tagName = document.activeElement.tagName.toLowerCase();
  if (tagName === "input" || tagName === "textarea" || tagName === "select") {
    return;
  }

  // ESC 键 - 关闭当前打开的弹窗
  if (e.key === "Escape") {
    if (openDialogs.size > 0) {
      const dialogId = Array.from(openDialogs)[openDialogs.size - 1];
      closeDialog(dialogId);
      e.preventDefault();
    }
  }

  // 空格键 - 播放
  if (e.key === " " || e.code === "Space") {
    play();
    e.preventDefault();
  }
});

// 为自定义按钮添加键盘支持（Enter 和 Space 键）
$(document).on("keydown", '[role="button"], [role="switch"]', function (e) {
  if (e.key === "Enter" || e.key === " ") {
    $(this).click();
    e.preventDefault();
  }
});

// 初始化收藏按钮的 ARIA 状态
$(document).ready(function () {
  const isFavorited = $(".favorite").hasClass("favorite-active");
  updateFavoriteAria(isFavorited);
});

// ============ 本机播放器 UI 更新函数 ============

// 更新本机播放状态 UI
function updateWebPlayingUI() {
  const audioElement = document.getElementById("audio");
  const currentMusic = WebPlayer.getCurrentMusic();

  if (!audioElement) return;

  const isPlaying = !audioElement.paused;
  const statusText = isPlaying ? "【播放中】" : "【暂停】";

  $("#playering-music").text(statusText + (currentMusic || "无"));
}

// 更新本机收藏按钮状态
function updateWebFavoriteButton() {
  const currentMusic = WebPlayer.getCurrentMusic();

  if (!currentMusic) return;

  // 直接使用全局 favoritelist，数据来源于服务器
  const isFavorited = favoritelist.includes(currentMusic);

  if (isFavorited) {
    $(".favorite").addClass("favorite-active");
  } else {
    $(".favorite").removeClass("favorite-active");
  }

  updateFavoriteAria(isFavorited);
}

// ============ 本机播放器事件监听器 ============

// 初始化本机播放器
function initWebPlayer() {
  const audioElement = document.getElementById("audio");

  if (!audioElement) {
    console.error("Audio element not found");
    return;
  }

  // 从 localStorage 恢复音量
  const savedVolume = WebPlayer.getVolume();
  audioElement.volume = savedVolume / 100;
  $("#volume").val(savedVolume);
  updateVolumeAria(savedVolume);

  // 从 localStorage 恢复播放模式
  const savedMode = WebPlayer.getPlayMode();
  const modeBtnIcon = $("#modeBtn .material-icons");
  modeBtnIcon.text(playModes[savedMode].icon);
  $("#modeBtn .tooltip").text(playModes[savedMode].cmd);

  // 设置单曲循环模式
  if (savedMode === 0) {
    audioElement.loop = true;
  }

  // 监听播放事件
  audioElement.addEventListener("play", function () {
    console.log("Audio play event");
    updateWebPlayingUI();
  });

  // 监听暂停事件
  audioElement.addEventListener("pause", function () {
    console.log("Audio pause event");
    updateWebPlayingUI();
  });

  // 监听播放结束事件
  audioElement.addEventListener("ended", function () {
    console.log("Audio ended event triggered");

    const playMode = WebPlayer.getPlayMode();
    console.log("Current play mode:", playMode, playModes[playMode].cmd);

    // 单曲循环模式下，loop 属性会自动处理，不需要手动处理
    if (playMode === 0) {
      console.log("Single loop mode, audio.loop will handle it");
      return;
    }

    // 单曲播放模式：不自动播放下一首
    if (playMode === 3) {
      console.log("Single play mode, stop after current song");
      updateWebPlayingUI();
      return;
    }

    // 顺序播放模式：到末尾停止
    if (playMode === 4) {
      const playList = WebPlayer.getPlayList();
      const currentIndex = WebPlayer.getCurrentIndex();
      console.log(
        "Sequential play mode, current index:",
        currentIndex,
        "playlist length:",
        playList.length,
      );
      if (currentIndex >= playList.length - 1) {
        console.log("Reached end of playlist, stop playing");
        updateWebPlayingUI();
        return;
      }
    }

    // 其他模式：自动播放下一首
    console.log("Auto playing next song...");
    webPlayNext();
  });

  // 监听时间更新事件
  audioElement.addEventListener("timeupdate", function () {
    const currentTime = audioElement.currentTime;
    const duration = audioElement.duration;

    // 检查是否为流媒体（duration 为 Infinity）
    const isStream = !isFinite(duration);

    if (isStream) {
      // 流媒体：只显示当前播放时间，不显示进度条
      $("#current-time").text(formatTime(currentTime));
      $("#duration").text("直播流");
      $("#progress").val(0); // 进度条设为 0
      console.log("Stream playing, current time:", currentTime);
    } else if (duration > 0) {
      // 普通音频：显示进度条和时长
      const progressPercent = (currentTime / duration) * 100;
      $("#progress").val(progressPercent);
      $("#current-time").text(formatTime(currentTime));
      $("#duration").text(formatTime(duration));

      // 更新 ARIA 属性
      updateProgressAria(currentTime, duration);
    }
  });

  // 监听元数据加载事件
  audioElement.addEventListener("loadedmetadata", function () {
    const duration = audioElement.duration;
    console.log("Audio metadata loaded, duration:", duration);

    // 检查是否为流媒体
    const isStream = !isFinite(duration);

    if (isStream) {
      // 流媒体：显示特殊标识
      $("#duration").text("直播流");
      $("#progress").val(0);
      $("#current-time").text("0:00");
      console.log("Stream detected");
    } else if (duration > 0) {
      // 普通音频文件
      $("#duration").text(formatTime(duration));
      $("#progress").val(0);
      $("#current-time").text("0:00");
    } else {
      // 无效的 duration
      $("#duration").text("0:00");
      $("#progress").val(0);
      $("#current-time").text("0:00");
    }
  });

  // 监听错误事件（已有，但确保本机播放也能正确处理）
  // 原有的 error 事件监听器已经存在，不需要重复添加

  console.log("Web player initialized");
}

// 页面加载完成后初始化本机播放器
$(document).ready(function () {
  // 等待设备选择器初始化完成后再执行
  setTimeout(function () {
    var did = $("#did").val();

    if (did == "web_device") {
      initWebPlayer();

      // 恢复上次播放的歌曲信息（仅显示，不自动播放）
      const lastMusic = WebPlayer.getCurrentMusic();
      if (lastMusic) {
        updateWebPlayingUI();
        updateWebFavoriteButton();
      }
    }
  }, 100);
});

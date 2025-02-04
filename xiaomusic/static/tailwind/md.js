// $(function () {

// })
let isPlaying = false;
let playModeIndex = 2;
//重新设计playModes
const playModes = {
  0: {
    icon: "repeat_one",
    cmd: "单曲循环"
  },
  1: {
    icon: "repeat",
    cmd: "全部循环"
  },
  2: {
    icon: "shuffle",
    cmd: "随机播放"
  },
  3: {
    icon: "looks_one",
    cmd: "单曲播放"
  },
  4: {
    icon: "queue_music",
    cmd: "顺序播放"
  }
};

let favoritelist = []; //收藏列表
let progressInterval;

// 全局变量，用于存储播放状态更新定时器
let playingStatusInterval = null;

function startProgressUpdate() {
  // 清除之前的计时器
  if (progressInterval) {
    clearInterval(progressInterval);
  }
  
  // 每秒更新一次进度条
  progressInterval = setInterval(() => {
    if (duration > 0) {
      offset += 1;
      if (offset <= duration) {
        // 更新进度条
        $("#progress").val((offset / duration) * 100);
        // 更新时间显示
        $("#current-time").text(formatTime(offset));
      } else {
        // 如果到达结尾，清除计时器
        clearInterval(progressInterval);
      }
    }
  }, 1000);
}

function stopProgressUpdate() {
  if (progressInterval) {
    clearInterval(progressInterval);
  }
}

// 播放音乐
window.playMusic = function(songName) {
  const currentPlaylist = localStorage.getItem("cur_playlist");
  console.log(`播放音乐: ${songName}, 播放列表: ${currentPlaylist}`);
  
  // 检查是否是当前播放的歌曲
  const currentPlayingSong = localStorage.getItem("cur_music");
  const isCurrentSong = currentPlayingSong === songName;
  
  if (window.did === 'web_device') {
    // Web播放模式
    $.get(`/musicinfo?name=${songName}`, function (data, status) {
      if (data.ret == "OK") {
        if (validHost(data.url)) {
          const audio = $("#audio")[0];
          
          // 如果是同一首歌，切换播放/暂停状态
          if (audio.src && audio.src === data.url) {
            if (audio.paused) {
              audio.play();
              $(".play").text("pause_circle_outline");
              updatePlayingInfo(songName, true);
            } else {
              audio.pause();
              $(".play").text("play_circle_outline");
              updatePlayingInfo(songName, false);
            }
          } else {
            // 播放新的歌曲
            audio.src = data.url;
            audio.play();
            $(".play").text("pause_circle_outline");
            updatePlayingInfo(songName, true);
          }
        }
      }
    });
  } else {
    // 设备播放模式
    if (isCurrentSong) {
      // 如果是当前播放的歌曲，发送暂停/继续命令
      sendcmd("暂停播放");
      // 切换按钮图标和高亮状态
      const songItem = $(`.song-item h3:contains('${songName}')`).closest('.song-item');
      const playButton = songItem.find("button .material-icons");
      if (playButton.text() === "pause") {
        playButton.text("play_arrow");
        updatePlayingInfo(songName, false);
      } else {
        playButton.text("pause");
        updatePlayingInfo(songName, true);
      }
    } else {
      // 播放新的歌曲
      do_play_music_list(currentPlaylist, songName);
      // 更新播放信息
      updatePlayingInfo(songName, true);
    }
  }
}

// 播放音乐列表
function do_play_music_list(listname, musicname) {
  $.ajax({
    type: "POST",
    url: "/playmusiclist",
    contentType: "application/json; charset=utf-8",
    data: JSON.stringify({
      did: window.did,
      listname: listname,
      musicname: musicname
    }),
    success: () => {
      console.log("播放成功", listname, musicname);
      // 更新播放信息
      updatePlayingInfo(musicname, true);
    },
    error: () => {
      console.log("播放失败", listname, musicname);
    }
  });
}

// 更新播放信息
function updatePlayingInfo(songName, isPlaying) {
  if (!songName) return;
  
  // 更新播放栏信息
  const displayText = isPlaying ? `【播放中】 ${songName}` : `【暂停中】 ${songName}`;
  $("#playering-music").text(displayText);
  $("#playering-music-mobile").text(displayText);
  
  // 更新播放按钮图标
  $(".play").text(isPlaying ? "pause_circle_outline" : "play_circle_outline");
  
  // 更新收藏状态
  updateFavoriteStatus(songName);
  
  // 高亮当前播放的歌曲
  highlightPlayingSong(songName, isPlaying);
  
  // 保存当前播放的歌曲
  localStorage.setItem("cur_music", songName);
  localStorage.setItem("is_playing", isPlaying);
  
  // 根据播放状态控制进度条更新
  if (isPlaying) {
    startProgressUpdate();
  } else {
    stopProgressUpdate();
  }
}

// 高亮当前播放的歌曲
function highlightPlayingSong(songName, isPlaying) {
  // 移除所有歌曲的高亮状态
  $(".song-item").removeClass("bg-blue-50 dark:bg-blue-900/20");
  
  // 重置所有播放按钮为播放图标（只选择播放按钮中的图标）
  $(".play-icon").text("play_arrow");
  
  // 高亮当前歌曲，无论是播放还是暂停状态
  $(".song-item").each(function() {
    const itemSongName = $(this).find("h3").text();
    if (itemSongName === songName) {
      // 始终添加高亮背景
      $(this).addClass("bg-blue-50 dark:bg-blue-900/20 dark:text-blue-400");
      // 根据播放状态更新播放按钮图标
      $(this).find(".play-icon").text(isPlaying ? "pause" : "play_arrow");
    }
  });
}

function webPlay() {
  console.log("webPlay");
  const music_name = $("#music_name").val();
  $.get(`/musicinfo?name=${music_name}`, function (data, status) {
    console.log(data);
    if (data.ret == "OK") {
      validHost(data.url) && $("audio").attr("src", data.url);
    }
  });
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
        validHost(data.url)
      );
      validHost(data.url) && do_play_music_list(music_list, music_name);
    }
  });
}
function stopPlay() {
  sendcmd("关机");
}

function prevTrack() {
  sendcmd("上一首");
}

function nextTrack() {
  sendcmd("下一首");
}

function togglePlayMode(isSend = true) {
  console.log('切换播放模式...');
  
  // 从本地存储获取当前播放模式，如果没有则使用默认值2（随机播放）
  if (playModeIndex === undefined || playModeIndex === null) {
    playModeIndex = parseInt(localStorage.getItem("playModeIndex")) || 2;
  }
  
  // 计算下一个播放模式索引：2 -> 3 -> 4 -> 2
  const nextModeIndex = playModeIndex >= 4 ? 2 : playModeIndex + 1;
  
  // 获取下一个播放模式
  const nextMode = playModes[nextModeIndex];
  console.log('切换到播放模式:', nextModeIndex, nextMode.cmd);
  
  // 更新按钮图标和提示文本
  const modeBtn = $("#modeBtn");
  const modeBtnIcon = modeBtn.find(".material-icons");
  const tooltip = modeBtn.find(".tooltip");
  
  modeBtnIcon.text(nextMode.icon);
  tooltip.text(nextMode.cmd);
  
  // 如果需要发送命令，则发送到设备
  if (isSend && window.did !== 'web_device') {
    console.log('发送播放模式命令:', nextMode.cmd);
    sendcmd(nextMode.cmd);
  }
  
  // 保存新的播放模式到本地存储和全局变量
  localStorage.setItem("playModeIndex", nextModeIndex);
  playModeIndex = nextModeIndex;
}

function addToFavorites() {
  const currentSong = localStorage.getItem("cur_music");
  if (!currentSong) return;

  const isLiked = favoritelist.includes(currentSong);
  const cmd = isLiked ? "取消收藏" : "加入收藏";
  
  // 发送收藏命令
  $.ajax({
    type: "POST",
    url: "/cmd",
    contentType: "application/json; charset=utf-8",
    data: JSON.stringify({
      did: window.did,
      cmd: cmd
    }),
    success: () => {
      console.log(`${cmd}成功: ${currentSong}`);
      
      // 更新本地收藏列表
      if (isLiked) {
        // 取消收藏
        favoritelist = favoritelist.filter(item => item !== currentSong);
        $(".favorite").removeClass("favorite-active");
      } else {
        // 添加收藏
        if (!favoritelist.includes(currentSong)) {
          favoritelist.push(currentSong);
        }
        $(".favorite").addClass("favorite-active");
      }
      
      // 如果当前在收藏列表页面，刷新列表
      if (localStorage.getItem("cur_playlist") === "收藏") {
        refresh_music_list();
      }
    },
    error: () => {
      console.error(`${cmd}失败: ${currentSong}`);
    }
  });
}

function openSettings() {
  console.log("打开设置");
  //新建标签页打开setting.html页面
  window.open("setting.html", "_blank");
}
function toggleVolume() {
  $("#volume-component").toggle();
}

function toggleSearch() {
  $("#search-component").toggle();
}
function toggleTimer() {
  $("#timer-component").toggle();
}
function togglePlayLink() {
  $("#playlink-component").toggle(); // 切换播放链接的显示状态
}
function toggleLocalPlay() {
  $("#audio").fadeIn();
}
function toggleWarning() {
  $("#warning-component").toggle(); // 切换警告框的显示状态
}
function toggleDelete() {
  var del_music_name = $("#music_name").val();
  $("#delete-music-name").text(del_music_name);
  $("#delete-component").toggle(); // 切换删除框的显示状态
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
  const minutes = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${minutes}:${secs < 10 ? "0" : ""}${secs}`; // Format time as mm:ss
}

var offset = 0;
var duration = 0;
let no_warning = localStorage.getItem("no-warning");
// 拉取现有配置
$.get("/getsetting", function (data, status) {
  console.log(data, status);
  localStorage.setItem("mi_did", data.mi_did);

  var did = localStorage.getItem("cur_did");
  var dids = [];
  if (data.mi_did != null) {
    dids = data.mi_did.split(",");
  }
  
  if (did != "web_device" && dids.length > 0 && (did == null || did == "" || !dids.includes(did))) {
    did = dids[0];
    localStorage.setItem("cur_did", did);
  }

  window.did = did;
  
  // 渲染设备按钮
  renderDeviceButtons(data.devices, did);
  
  // 获取音量
  $.get(`/getvolume?did=${did}`, function (data, status) {
    console.log(data, status, data["volume"]);
    $("#volume").val(data.volume);
  });
  
  // 刷新音乐列表
  refresh_music_list();

  if (did == "web_device") {
    $("#audio").fadeIn();
    $("#device-audio").fadeOut();
    $(".device-enable").addClass('disabled');
  } else {
    $("#audio").fadeOut();
    $("#device-audio").fadeIn();
    $(".device-enable").removeClass('disabled');
  }
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
    if (!data) {
      console.error("未获取到音乐列表数据");
      return;
    }
    
    favoritelist = data["收藏"] || [];

    // 设置默认播放列表
    const defaultList = "所有歌曲";
    if (!localStorage.getItem("cur_playlist")) {
      localStorage.setItem("cur_playlist", defaultList);
      showPlaylist(defaultList);
    }

    // 渲染系统播放列表和专辑列表
    renderSystemPlaylists(data);
    renderAlbumList(data);

    // 获取当前播放列表
    $.get(`/curplaylist?did=${window.did}`, function(playlist, status) {
      if (playlist && playlist !== "") {
        localStorage.setItem("cur_playlist", playlist);
        showPlaylist(playlist);
      } else {
        // 使用本地记录的播放列表
        const savedPlaylist = localStorage.getItem("cur_playlist") || defaultList;
        if (data.hasOwnProperty(savedPlaylist)) {
          showPlaylist(savedPlaylist);
        } else {
          showPlaylist(defaultList);
        }
      }
      callback && callback();
    });
  });
}

// 渲染系统播放列表
function renderSystemPlaylists(data) {
  const container = $("#system-playlists");
  if (!container.length) {
    console.error("未找到系统播放列表容器");
    return;
  }

  const systemPlaylists = [
    { name: '所有歌曲', icon: 'queue_music' },
    { name: '收藏', icon: 'favorite' },
    { name: '最近新增', icon: 'new_releases' },
    { name: '下载', icon: 'download' }
  ];

  container.empty().addClass('flex flex-wrap gap-2');

  // 获取当前播放列表，如果没有则默认为"所有歌曲"
  const defaultList = "所有歌曲";
  let currentPlaylist = localStorage.getItem("cur_playlist");
  if (!currentPlaylist) {
    currentPlaylist = defaultList;
    localStorage.setItem("cur_playlist", defaultList);
  }

  systemPlaylists.forEach(playlist => {
    const songs = data[playlist.name] || [];
    const count = songs.length;
    const isActive = playlist.name === currentPlaylist;
    
    const button = $(`
      <button 
        onclick="showPlaylist('${playlist.name}')" 
        class="flex items-center p-2 rounded-md transition-colors ${
          isActive 
            ? 'bg-blue-50 dark:bg-blue-900/20 text-blue-600 dark:text-blue-400' 
            : 'hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-700 dark:text-white'
        }"
      >
        <span class="material-icons">${playlist.icon}</span>
        <span class="ml-2 hidden md:inline">
          ${playlist.name}
          <span class="text-xs ${
            isActive 
              ? 'text-blue-500 dark:text-blue-400'
              : 'text-gray-500 dark:text-gray-400'
          }">(${count})</span>
        </span>
        ${isActive ? '<span class="material-icons ml-2 text-blue-500 text-sm hidden md:inline">check</span>' : ''}
      </button>
    `);
    
    container.append(button);
  });
}

// 渲染专辑列表
function renderAlbumList(data) {
  const container = $("#album-list");
  
  if (!data || typeof data !== 'object') {
    return;
  }
  
  container.empty();
  
  // 系统预设的播放列表，这些不在专辑列表中显示
  const systemPlaylists = [
    '收藏', '最近新增', '所有歌曲', '临时搜索列表',
    '所有电台', '全部', '下载', '其他'
  ];
  
  const currentPlaylist = localStorage.getItem("cur_playlist");
  
  // 遍历所有播放列表
  for (const [listName, songs] of Object.entries(data)) {
    // 跳过系统预设列表
    if (systemPlaylists.includes(listName)) {
      continue;
    }
    
    // 跳过空列表
    if (songs.length === 0) {
      continue;
    }
    
    const isActive = listName === currentPlaylist;
    
    const button = $(`
      <button 
        onclick="showPlaylist('${listName}')" 
        class="w-full flex items-center space-x-3 p-2.5 rounded-md transition-colors group ${
          isActive 
            ? 'bg-blue-50 dark:bg-blue-900/20 text-blue-600 dark:text-blue-400' 
            : 'hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-700 dark:text-white'
        }"
      >
        <span class="material-icons flex-shrink-0 ${
          isActive 
            ? 'text-blue-600 dark:text-blue-400'
            : 'text-gray-500 dark:text-white'
        }">album</span>
        <span class="min-w-0 flex-1 truncate text-left">
          ${listName}
          <span class="text-xs ${
            isActive 
              ? 'text-blue-500 dark:text-blue-400'
              : 'text-gray-500 dark:text-gray-400'
          }">(${songs.length})</span>
        </span>
        ${isActive ? '<span class="material-icons flex-shrink-0 text-blue-500 text-sm">check</span>' : ''}
      </button>
    `);
    
    container.append(button);
  }
}

// 显示播放列表
window.showPlaylist = function(listName) {
  // 获取当前播放列表数据
  $.get("/musiclist", function (data, status) {
    if (!data || !data[listName]) {
      // 如果播放列表不存在，默认显示"所有歌曲"
      if (listName !== "所有歌曲") {
        showPlaylist("所有歌曲");
      }
      return;
    }

    // 渲染歌曲列表
    const songs = data[listName] || [];
    renderSongList(songs);
    
    // 保存当前播放列表
    localStorage.setItem("cur_playlist", listName);
    
    // 重新渲染系统播放列表和专辑列表以更新高亮状态
    renderSystemPlaylists(data);
    renderAlbumList(data);
  });
}

// 拉取播放列表
function refresh_music_list() {
  console.log("开始刷新音乐列表...");
  // 刷新列表时清空并临时禁用搜索框
  const searchInput = document.getElementById("search-input");
  if (!searchInput) {
    console.error("未找到搜索输入框");
    return;
  }
  
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
    // 立即获取一次播放状态
    get_playing_music();
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

$("#playurl").on("click", () => {
  var url = $("#music-url").val();
  const encoded_url = encodeURIComponent(url);
  $.get(`/playurl?url=${encoded_url}&did=${did}`, function (data, status) {
    console.log(data);
  });
});


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

// 调节音量
$("#volume").on("change", function () {
  var value = $(this).val();
  $.ajax({
    type: "POST",
    url: "/setvolume",
    contentType: "application/json; charset=utf-8",
    data: JSON.stringify({ did: did, volume: value }),
    success: () => { },
    error: () => { },
  });
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
          cmd
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
function handleSearch() {
  const searchInput = document.getElementById("search-input");
  if (!searchInput) {
    console.log("搜索输入框不存在");
    return;
  }

  searchInput.addEventListener(
    "input",
    debounce(function () {
      const query = searchInput.value.trim();
      const songItems = document.querySelectorAll('.song-item');

      songItems.forEach(item => {
        const songName = item.querySelector('h3')?.textContent.toLowerCase() || '';
        if (songName.includes(query.toLowerCase())) {
          item.style.display = '';
        } else {
          item.style.display = 'none';
        }
      });
    }, 300)
  );
}

// 在文档加载完成后初始化搜索功能
document.addEventListener('DOMContentLoaded', function() {
  handleSearch();
});

function get_playing_music() {
  $.get(`/playingmusic?did=${did}`, function (data, status) {
    console.log(data);
    if (data.ret == "OK" && data.cur_music) {  // 确保cur_music存在
      updatePlayingInfo(data.cur_music, data.is_playing);
      
      // 更新进度条和时间显示
      offset = data.offset || 0;
      duration = data.duration || 0;
      
      if (duration > 0) {
        // 更新进度条
        $("#progress").val((offset / duration) * 100);
        // 更新时间显示
        $("#current-time").text(formatTime(offset));
        $("#duration").text(formatTime(duration));
        
        // 如果正在播放，启动进度条更新
        if (data.is_playing) {
          startProgressUpdate();
        } else {
          stopProgressUpdate();
        }
      } else {
        // 如果没有时长信息，重置显示
        $("#progress").val(0);
        $("#current-time").text("00:00");
        $("#duration").text("00:00");
        stopProgressUpdate();
      }
      
      // 更新收藏状态
      if (favoritelist.includes(data.cur_music)) {
        $(".favorite").addClass("favorite-active");
      } else {
        $(".favorite").removeClass("favorite-active");
      }

      // 更新 Vue 组件状态
      const app = document.querySelector('#app')?.__vue_app__;
      if (app) {
        const vm = app._component;
        if (vm && vm.updatePlayingStatus) {
          vm.updatePlayingStatus();
        }
      }
    } else {
      // 如果没有正在播放的音乐，重置显示
      $("#progress").val(0);
      $("#current-time").text("00:00");
      $("#duration").text("00:00");
      offset = 0;
      duration = 0;
      stopProgressUpdate();
    }
  });
}

// 格式化时间
function formatTime(seconds) {
  const minutes = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${minutes.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
}

// 停止播放
window.stopPlay = function() {
  const currentSong = localStorage.getItem("cur_music");
  if (!currentSong) return;

  if (window.did === 'web_device') {
    const audio = $("#audio")[0];
    audio.pause();
    audio.currentTime = 0;
    updatePlayingInfo(currentSong, false);
  } else {
    // 设备播放模式
    sendcmd("停止");
    updatePlayingInfo(currentSong, false);
  }
  
  // 重置进度条和时间显示
  $("#progress").val(0);
  $("#current-time").text("00:00");
  $("#duration").text("00:00");
  offset = 0;
  duration = 0;
  stopProgressUpdate();
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
    e.currentTarget.error.message
  );
  alert(
    e.currentTarget.error.code == 4
      ? "无法打开媒体文件，XIAOMUSIC_HOSTNAME或端口地址错误，请重新设置"
      : "在线播放失败，请截图反馈: " + e.currentTarget.error.message
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

// 绑定点击事件，显示弹窗
$('#version').on('click', function () {
  $.get("https://xdocs.hanxi.cc/versions.json", function (data, status) {
    console.log(data);
    const versionSelect = document.getElementById("update-version");
    versionSelect.innerHTML = "";
    data.forEach((item) => {
      const option = document.createElement("option");
      option.value = item.version;
      option.textContent = item.version;
      versionSelect.appendChild(option);
    });
  });
  $('#update-component').show();
});

// 关闭更新弹窗
function toggleUpdate() {
  $('#update-component').hide();
}

function doUpdates() {
  const version = $("#update-version").val();
  let lite = $("#lite").val();
  $.ajax({
    type: "POST",
    url: `/updateversion?version=${version}&lite=${lite}`,
    contentType: "application/json; charset=utf-8",
    success: (data) => {
      if (data.ret == "OK") {
        alert(`更新成功,请刷新页面`);
        location.reload();
      } else {
        alert(`更新失败: ${data.ret}`);
      }
    },
    error: () => {
      alert(`更新失败`);
    },
  });
}

function confirmSearch() {
  var search_key = $("#search").val();
  if (search_key == null) {
    search_key = "";
  }
  var filename = $("#music-name").val();
  var musicfilename = $("#music-filename").val();
  if ((filename == null || filename == "" || filename == search_key)
    && (musicfilename != null && musicfilename != "")) {
    filename = musicfilename;
  }
  console.log("confirmSearch", filename, search_key);
  do_play_music(filename, search_key);
  toggleSearch();
}

// 主题切换功能
function toggleTheme() {
  const html = document.documentElement;
  if (html.classList.contains('dark')) {
    html.classList.remove('dark');
    localStorage.setItem('theme', 'light');
  } else {
    html.classList.add('dark');
    localStorage.setItem('theme', 'dark');
  }
}

// 初始化主题
function initTheme() {
  const theme = localStorage.getItem('theme');
  if (theme === 'dark' || (!theme && window.matchMedia('(prefers-color-scheme: dark)').matches)) {
    document.documentElement.classList.add('dark');
  }
}

// 音量调节功能
function adjustVolume(value) {
  // 更新本地音频音量（web播放模式）
  const audio = document.getElementById('audio');
  if (audio) {
    audio.volume = value;
    localStorage.setItem('volume', value);
  }
  
  // 更新设备音量
  if (window.did && window.did !== 'web_device') {
    $.ajax({
      type: "POST",
      url: "/setvolume",
      contentType: "application/json; charset=utf-8",
      data: JSON.stringify({ did: window.did, volume: Math.round(value * 100) }),
      success: () => {
        console.log('Volume set successfully');
      },
      error: () => {
        console.error('Failed to set volume');
      },
    });
  }
}

// 初始化音量
function initVolume() {
  // 获取存储的音量值或默认值
  const defaultVolume = 0.5;
  let volume = localStorage.getItem('volume');
  volume = volume ? parseFloat(volume) : defaultVolume;

  // 设置本地音频音量
  const audio = document.getElementById('audio');
  if (audio) {
    audio.volume = volume;
  }

  // 设置音量滑块值
  const volumeSlider = document.getElementById('volume-slider');
  if (volumeSlider) {
    volumeSlider.value = volume;
  }

  // 如果是设备播放模式，获取设备音量
  if (window.did && window.did !== 'web_device') {
    $.get(`/getvolume?did=${window.did}`, function (data, status) {
      if (data.volume !== undefined) {
        const deviceVolume = data.volume / 100;
        volumeSlider.value = deviceVolume;
        localStorage.setItem('volume', deviceVolume);
      }
    });
  }
}

// 移除旧的音量事件监听器
$("#volume").off("change");

// 添加新的音量事件监听器
document.getElementById('volume-slider')?.addEventListener('input', function() {
  adjustVolume(this.value);
});

// 渲染设备按钮
function renderDeviceButtons(devices, currentDid) {
  const container = $("#device-buttons");
  container.empty();
  
  // 切换设备函数
  function switchDevice(did) {
    // 只有在切换到不同设备时才刷新页面
    if (did !== currentDid) {
      localStorage.setItem('cur_did', did);
      window.did = did;
      location.reload();
    }
  }
  
  // 添加设备按钮
  Object.values(devices).forEach(device => {
    const isActive = device.did === currentDid;
    const button = $(`
      <button 
        data-did="${device.did}" 
        class="w-full flex items-center space-x-3 p-2.5 rounded-md transition-colors group ${
          isActive 
            ? 'bg-blue-50 dark:bg-blue-900/20 text-blue-600 dark:text-blue-400' 
            : 'hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-700 dark:text-white'
        }"
      >
        <span class="material-icons flex-shrink-0 ${
          isActive 
            ? 'text-blue-600 dark:text-blue-400'
            : 'text-gray-500 dark:text-white'
        }">
          ${isActive ? 'speaker_group' : 'speaker'}
        </span>
        <span class="min-w-0 flex-1 truncate text-left">
          ${device.name}
        </span>
        ${isActive ? '<span class="material-icons flex-shrink-0 text-blue-500 text-sm">check</span>' : ''}
      </button>
    `);
    
    button.click(function() {
      switchDevice(device.did);
    });
    
    container.append(button);
  });
  
  // 添加本机播放按钮
  const isWebDevice = currentDid === 'web_device';
  const webDeviceButton = $(`
    <button 
      data-did="web_device" 
      class="w-full flex items-center space-x-3 p-2.5 rounded-md transition-colors group ${
        isWebDevice 
          ? 'bg-blue-50 dark:bg-blue-900/20 text-blue-600 dark:text-blue-400' 
          : 'hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-700 dark:text-white'
      }"
    >
      <span class="material-icons flex-shrink-0 ${
        isWebDevice 
          ? 'text-blue-600 dark:text-blue-400'
          : 'text-gray-500 dark:text-white'
      }">
        ${isWebDevice ? 'computer' : 'desktop_windows'}
      </span>
      <span class="min-w-0 flex-1 truncate text-left">
        本机播放
      </span>
      ${isWebDevice ? '<span class="material-icons flex-shrink-0 text-blue-500 text-sm">check</span>' : ''}
    </button>
  `);
  
  webDeviceButton.click(function() {
    switchDevice('web_device');
  });
  
  container.append(webDeviceButton);
}

// 显示播放列表
function showPlaylist(type) {
  // 移除所有按钮的活动状态
  $('.playlist-button').removeClass('bg-blue-50 dark:bg-blue-900/20');
  // 添加当前按钮的活动状态
  $(`[data-playlist="${type}"]`).addClass('bg-blue-50 dark:bg-blue-900/20');
  
  switch(type) {
    case 'all':
      // 显示所有歌曲
      break;
    case 'favorites':
      // 显示收藏歌曲
      break;
    case 'recent':
      // 显示最近新增
      break;
  }
}

// 显示专辑内容
function showAlbum(albumName) {
  // 实现显示专辑内容的逻辑
}

// 导出函数
window.toggleTheme = toggleTheme;
window.initTheme = initTheme;
window.adjustVolume = adjustVolume;
window.initVolume = initVolume;

// 添加删除按钮显示状态变量
let showDeleteButtons = false;

// 切换删除按钮显示状态
window.toggleDeleteButtons = function() {
  showDeleteButtons = !showDeleteButtons;
  // 更新所有删除按钮的显示状态
  $(".delete-button").toggleClass("hidden", !showDeleteButtons);
}

// 渲染歌曲列表
function renderSongList(songs) {
  const container = $("#song-list");
  container.empty();

  if (!Array.isArray(songs)) {
    console.error("歌曲列表数据无效");
    return;
  }

  const currentSong = localStorage.getItem("cur_music");
  const isPlaying = localStorage.getItem("is_playing") === "true";

  songs.forEach(song => {
    const isCurrentSong = song === currentSong;
    const songItem = $(`
      <div class="song-item flex items-center justify-between p-3 ${
        isCurrentSong && isPlaying
          ? 'bg-blue-50 dark:bg-blue-900/20 dark:text-blue-400' 
          : 'bg-gray-200 dark:bg-gray-800 dark:text-white'
      } rounded-lg hover:bg-gray-300 dark:hover:bg-gray-700 transition-colors">
        <div class="flex items-center space-x-3 flex-1">
          <div class="w-10 h-10 bg-gray-300 dark:bg-gray-700 rounded flex items-center justify-center flex-shrink-0">
            <span class="material-icons song-icon text-gray-500 dark:text-gray-400">music_note</span>
          </div>
          <div class="min-w-0 flex-1">
            <h3 class="font-semibold truncate dark:text-blue-400">${song}</h3>
          </div>
        </div>
        <div class="flex items-center space-x-2">
          <button class="play-button w-10 h-10 flex items-center justify-center rounded-full hover:bg-gray-400 dark:hover:bg-gray-600 transition-colors">
            <span class="material-icons play-icon text-gray-600 dark:text-gray-300">${isCurrentSong && isPlaying ? 'pause' : 'play_arrow'}</span>
            </button>
          <button class="delete-button w-10 h-10 flex items-center justify-center rounded-full hover:bg-red-400 dark:hover:bg-red-600 transition-colors ${showDeleteButtons ? '' : 'hidden'}">
            <span class="material-icons text-gray-600 dark:text-gray-300 hover:text-white">delete</span>
            </button>
          </div>
        </div>
    `);
    
    // 添加播放按钮点击事件
    songItem.find('.play-button').on('click', function() {
      playMusic(song);
    });
    
    // 添加删除按钮点击事件
    songItem.find('.delete-button').on('click', function() {
      if (confirm(`确定要删除歌曲 "${song}" 吗？`)) {
        $.ajax({
          type: "POST",
          url: "/delmusic",
          data: JSON.stringify({ name: song }),
          contentType: "application/json; charset=utf-8",
          success: () => {
            console.log(`删除歌曲 ${song} 成功`);
            refresh_music_list();
          },
          error: () => {
            console.error(`删除歌曲 ${song} 失败`);
            alert(`删除歌曲 ${song} 失败`);
          },
        });
      }
    });
    
    container.append(songItem);
  });
}

// 播放音乐
window.playMusic = function(songName) {
  const currentPlaylist = localStorage.getItem("cur_playlist");
  console.log(`播放音乐: ${songName}, 播放列表: ${currentPlaylist}`);
  
  // 检查是否是当前播放的歌曲
  const currentPlayingSong = localStorage.getItem("cur_music");
  const isCurrentSong = currentPlayingSong === songName;
  
  if (window.did === 'web_device') {
    // Web播放模式
    $.get(`/musicinfo?name=${songName}`, function (data, status) {
      if (data.ret == "OK") {
        if (validHost(data.url)) {
          const audio = $("#audio")[0];
          
          // 如果是同一首歌，切换播放/暂停状态
          if (audio.src && audio.src === data.url) {
            if (audio.paused) {
              audio.play();
              $(".play").text("pause_circle_outline");
              updatePlayingInfo(songName, true);
            } else {
              audio.pause();
              $(".play").text("play_circle_outline");
              updatePlayingInfo(songName, false);
            }
          } else {
            // 播放新的歌曲
            audio.src = data.url;
            audio.play();
            $(".play").text("pause_circle_outline");
            updatePlayingInfo(songName, true);
          }
        }
      }
    });
  } else {
    // 设备播放模式
    if (isCurrentSong) {
      // 如果是当前播放的歌曲，发送暂停/继续命令
      sendcmd("暂停播放");
      // 切换按钮图标和高亮状态
      const songItem = $(`.song-item h3:contains('${songName}')`).closest('.song-item');
      const playButton = songItem.find("button .material-icons");
      if (playButton.text() === "pause") {
        playButton.text("play_arrow");
        updatePlayingInfo(songName, false);
      } else {
        playButton.text("pause");
        updatePlayingInfo(songName, true);
      }
    } else {
      // 播放新的歌曲
      do_play_music_list(currentPlaylist, songName);
      // 更新播放信息
      updatePlayingInfo(songName, true);
    }
  }
}

// 更新播放信息
function updatePlayingInfo(songName, isPlaying) {
  if (!songName) return;
  
  // 更新播放栏信息
  const displayText = isPlaying ? `【播放中】 ${songName}` : `【暂停中】 ${songName}`;
  $("#playering-music").text(displayText);
  $("#playering-music-mobile").text(displayText);
  
  // 更新播放按钮图标
  $(".play").text(isPlaying ? "pause_circle_outline" : "play_circle_outline");
  
  // 更新收藏状态
  updateFavoriteStatus(songName);
  
  // 高亮当前播放的歌曲
  highlightPlayingSong(songName, isPlaying);
  
  // 保存当前播放的歌曲
  localStorage.setItem("cur_music", songName);
  localStorage.setItem("is_playing", isPlaying);
  
  // 根据播放状态控制进度条更新
  if (isPlaying) {
    startProgressUpdate();
  } else {
    stopProgressUpdate();
  }
}

// 高亮当前播放的歌曲
function highlightPlayingSong(songName, isPlaying) {
  // 移除所有歌曲的高亮状态
  $(".song-item").removeClass("bg-blue-50 dark:bg-blue-900/20");
  
  // 重置所有播放按钮为播放图标（只选择播放按钮中的图标）
  $(".play-icon").text("play_arrow");
  
  // 高亮当前歌曲，无论是播放还是暂停状态
  $(".song-item").each(function() {
    const itemSongName = $(this).find("h3").text();
    if (itemSongName === songName) {
      // 始终添加高亮背景
      $(this).addClass("bg-blue-50 dark:bg-blue-900/20");
      // 根据播放状态更新播放按钮图标
      $(this).find(".play-icon").text(isPlaying ? "pause" : "play_arrow");
    }
  });
}

// 播放/暂停切换
window.play = function() {
  const currentSong = localStorage.getItem("cur_music");
  if (!currentSong) return;

  if (window.did === 'web_device') {
    const audio = $("#audio")[0];
    if (audio.paused) {
      audio.play();
      updatePlayingInfo(currentSong, true);
    } else {
      audio.pause();
      updatePlayingInfo(currentSong, false);
    }
  } else {
    // 设备播放模式
    const isPlaying = localStorage.getItem("is_playing") === "true";
    const currentPlaylist = localStorage.getItem("cur_playlist");
    if (!currentPlaylist) return;

    if (isPlaying) {
      // 如果正在播放，则暂停
      sendcmd("暂停播放");
      updatePlayingInfo(currentSong, false);
    } else {
      // 如果已暂停，则继续播放
      do_play_music_list(currentPlaylist, currentSong);
      updatePlayingInfo(currentSong, true);
    }
  }
}

// 停止播放
window.stopPlay = function() {
  const currentSong = localStorage.getItem("cur_music");
  if (!currentSong) return;

  if (window.did === 'web_device') {
    const audio = $("#audio")[0];
    audio.pause();
    audio.currentTime = 0;
    updatePlayingInfo(currentSong, false);
  } else {
    // 设备播放模式
    sendcmd("停止");
    updatePlayingInfo(currentSong, false);
  }
  
  // 重置进度条和时间显示
  $("#progress").val(0);
  $("#current-time").text("00:00");
  $("#duration").text("00:00");
  offset = 0;
  duration = 0;
  stopProgressUpdate();
}

// 关机
window.shutdown = function() {
  const currentSong = localStorage.getItem("cur_music");
  if (!currentSong) return;

  if (window.did === 'web_device') {
    const audio = $("#audio")[0];
    audio.pause();
    audio.currentTime = 0;
    updatePlayingInfo(currentSong, false);
  } else {
    // 设备播放模式
    sendcmd("关机");
    updatePlayingInfo(currentSong, false);
  }
}

// 上一首
window.prevTrack = function() {
  if (window.did === 'web_device') {
    // Web播放模式的上一首逻辑
    const currentPlaylist = localStorage.getItem("cur_playlist");
    $.get("/musiclist", function (data, status) {
      if (!data || !data[currentPlaylist]) return;
      
      const songs = data[currentPlaylist];
      const currentSong = $("#playering-music").text().replace('当前播放歌曲：', '');
      const currentIndex = songs.indexOf(currentSong);
      const prevIndex = currentIndex > 0 ? currentIndex - 1 : songs.length - 1;
      
      playMusic(songs[prevIndex]);
    });
  } else {
    sendcmd("上一首");
  }
}

// 下一首
window.nextTrack = function() {
  if (window.did === 'web_device') {
    // Web播放模式的下一首逻辑
    const currentPlaylist = localStorage.getItem("cur_playlist");
    $.get("/musiclist", function (data, status) {
      if (!data || !data[currentPlaylist]) return;
      
      const songs = data[currentPlaylist];
      const currentSong = $("#playering-music").text().replace('当前播放歌曲：', '');
      const currentIndex = songs.indexOf(currentSong);
      const nextIndex = currentIndex < songs.length - 1 ? currentIndex + 1 : 0;
      
      playMusic(songs[nextIndex]);
    });
  } else {
    sendcmd("下一首");
  }
}

// 切换收藏状态
window.toggleFavorite = function() {
  const currentSong = document.getElementById('playering-music')?.textContent.replace('当前播放歌曲：', '').trim();
  if (!currentSong || currentSong === '无') return;

  const favoriteIcon = document.querySelector('.favorite-icon');
  const isFavorite = favoriteIcon.textContent === 'favorite';
  
  // 切换图标
  favoriteIcon.textContent = isFavorite ? 'favorite_border' : 'favorite';
  
  // 发送收藏/取消收藏请求
  $.ajax({
    type: "POST",
    url: "/togglefavorite",
    contentType: "application/json; charset=utf-8",
    data: JSON.stringify({
      song: currentSong,
      action: isFavorite ? 'remove' : 'add'
    }),
    success: () => {
      console.log(`${isFavorite ? '取消收藏' : '收藏'}成功:`, currentSong);
      // 刷新播放列表以更新收藏状态
      refresh_music_list();
    },
    error: () => {
      console.error(`收藏失败:`, currentSong);
    }
  });
}

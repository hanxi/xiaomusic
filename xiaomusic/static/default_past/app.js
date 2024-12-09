$(function(){
  $container=$("#cmds");

  append_op_button_name("加入收藏");
  append_op_button_name("取消收藏");

  append_op_button_name("上一首");
  append_op_button_name("关机");
  append_op_button_name("下一首");

  const PLAY_TYPE_ONE = 0; // 单曲循环
  const PLAY_TYPE_ALL = 1; // 全部循环
  const PLAY_TYPE_RND = 2; // 随机播放
  const PLAY_TYPE_SIN = 3; // 单曲播放
  const PLAY_TYPE_SEQ = 4; // 顺序播放
  append_op_button("play_type_all", "全部循环", "全部循环");
  append_op_button("play_type_one", "单曲循环", "单曲循环");
  append_op_button("play_type_rnd", "随机播放", "随机播放");
  append_op_button("play_type_sin", "单曲播放", "单曲播放");
  append_op_button("play_type_seq", "顺序播放", "顺序播放");

  append_op_button_name("刷新列表");

  $container.append($("<hr>"));

  append_op_button_name("10分钟后关机");
  append_op_button_name("30分钟后关机");
  append_op_button_name("60分钟后关机");

  var offset = 0;
  var duration = 0;
  let no_warning = localStorage.getItem('no-warning');
  // 拉取现有配置
  $.get("/getsetting", function(data, status) {
    console.log(data, status);
    localStorage.setItem('mi_did', data.mi_did);

    var did = localStorage.getItem('cur_did');
    var dids = [];
    if (data.mi_did != null) {
      dids = data.mi_did.split(',');
    }
    console.log('cur_did', did);
    console.log('dids', dids);
    if ((dids.length > 0) && (did == null || did == "" || !dids.includes(did))) {
      did = dids[0];
      localStorage.setItem('cur_did', did);
    }

    window.did = did;
    $.get(`/getvolume?did=${did}`, function(data, status) {
      console.log(data, status, data["volume"]);
      $("#volume").val(data.volume);
    });
    refresh_music_list();

    $("#did").empty();
    var dids = data.mi_did.split(',');
    $.each(dids, function(index, value) {
      var cur_device = Object.values(data.devices).find(device => device.did === value);
      if (cur_device) {
        var option = $('<option></option>')
            .val(value)
            .text(cur_device.name)
            .prop('selected', value === did);
        $("#did").append(option);

        if (value === did) {
          if (cur_device.play_type == PLAY_TYPE_ALL) {
            $("#play_type_all").css('background-color', '#b1a8f3');
            $("#play_type_all").text('✔️ 全部循环');
          } else if (cur_device.play_type == PLAY_TYPE_ONE) {
            $("#play_type_one").css('background-color', '#b1a8f3');
            $("#play_type_one").text('✔️ 单曲循环');
          } else if (cur_device.play_type == PLAY_TYPE_RND) {
            $("#play_type_rnd").css('background-color', '#b1a8f3');
            $("#play_type_rnd").text('✔️ 随机播放');
          } else if (cur_device.play_type == PLAY_TYPE_SIN) {
            $("#play_type_sin").css('background-color', '#b1a8f3');
            $("#play_type_sin").text('✔️ 单曲播放');
          } else if (cur_device.play_type == PLAY_TYPE_SEQ) {
            $("#play_type_seq").css('background-color', '#b1a8f3');
            $("#play_type_seq").text('✔️ 顺序播放');
          }
        }
      }
    });

    console.log('cur_did', did);
    $('#did').change(function() {
      did = $(this).val();
      localStorage.setItem('cur_did', did);
      window.did = did;
      console.log('cur_did', did);
      location.reload();
    })
  });

  function compareVersion(version1, version2) {
    const v1 = version1.split('.').map(Number);
    const v2 = version2.split('.').map(Number);
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
  $.get("/getversion", function(data, status) {
    console.log(data, status, data["version"]);
    $("#version").text(`${data.version}`);

    $.get("/latestversion", function(ret, status) {
      console.log(ret, status);
      if (ret.ret == "OK") {
        const result = compareVersion(ret.version, data.version);
        if (result > 0) {
          console.log(`${ret.version} is greater than ${data.version}`);
          $("#versionnew").text("🆕");
        }
      }
    });
  });

  function _refresh_music_list(callback) {
    $('#music_list').empty();
    $.get("/musiclist", function(data, status) {
      console.log(data, status);
      $.each(data, function(key, value) {
        let cnt = value.length;
        $('#music_list').append($('<option></option>').val(key).text(`${key} (${cnt})`));
      });

      $('#music_list').change(function() {
        const selectedValue = $(this).val();
        localStorage.setItem('cur_playlist', selectedValue);
        $('#music_name').empty();
        $.each(data[selectedValue], function(index, item) {
          $('#music_name').append($('<option></option>').val(item).text(item));
        });
      });

      $('#music_list').trigger('change');

      // 获取当前播放列表
      $.get(`/curplaylist?did=${did}`, function(playlist, status) {
        if (playlist != "") {
          $('#music_list').val(playlist);
          $('#music_list').trigger('change');
        } else {
          // 使用本地记录的
          playlist = localStorage.getItem('cur_playlist');
          if (data.hasOwnProperty(playlist)) {
            $('#music_list').val(playlist);
            $('#music_list').trigger('change');
          }
        }
      })
      callback();
    })
  }

  // 拉取播放列表
  function refresh_music_list() {
    // 刷新列表时清空并临时禁用搜索框
    const searchInput = document.getElementById('search');
    const oriPlaceHolder = searchInput.placeholder
    const oriValue = searchInput.value
    const inputEvent = new Event('input', { bubbles: true });
    searchInput.value = '';
    // 分发事件，让其他控件改变状态
    searchInput.dispatchEvent(inputEvent);
    searchInput.disabled = true;
    searchInput.placeholder = '请等待...';

    _refresh_music_list(() => {
      // 刷新完成再启用
      searchInput.disabled = false;
      searchInput.value = oriValue
      searchInput.dispatchEvent(inputEvent);
      searchInput.placeholder = oriPlaceHolder;
      // 每3秒获取下正在播放的音乐
      get_playing_music();
      setInterval(() => {
        get_playing_music();
      }, 3000);
    });
  }

  function do_play_music_list(listname, musicname) {
    $.ajax({
      type: "POST",
      url: "/playmusiclist",
      contentType: "application/json; charset=utf-8",
      data: JSON.stringify({did: did, listname: listname, musicname: musicname}),
      success: () => {
        console.log("do_play_music_list succ", listname, musicname);
      },
      error: () => {
        console.log("do_play_music_list failed", listname, musicname);
      }
    });
  }

  $("#play_music_list").on("click", () => {
    var music_list = $("#music_list").val();
    var music_name = $("#music_name").val();
    if (no_warning) {
      do_play_music_list(music_list, music_name);
      return;
    }
    $.get(`/musicinfo?name=${music_name}`, function(data, status) {
      console.log(data);
      if (data.ret == "OK") {
        validHost(data.url) && do_play_music_list(music_list, music_name);
      }
    });
  });

  $("#web_play").on("click", () => {
    const music_name = $("#music_name").val();
    $.get(`/musicinfo?name=${music_name}`, function(data, status) {
      console.log(data);
      if (data.ret == "OK") {
        validHost(data.url) && $('audio').attr('src',data.url);
      }
    });
  });

  $("#del_music").on("click", () => {
    var del_music_name = $("#music_name").val();
    if (confirm(`确定删除歌曲 ${del_music_name} 吗？`)) {
      console.log(`删除歌曲 ${del_music_name}`);
      $.ajax({
        type: 'POST',
        url: '/delmusic',
        data: JSON.stringify({"name": del_music_name}),
        contentType: "application/json; charset=utf-8",
        success: () => {
          alert(`删除 ${del_music_name} 成功`);
          refresh_music_list();
        },
        error: () => {
          alert(`删除 ${del_music_name} 失败`);
        }
      });
    }
  });

  $("#playurl").on("click", () => {
    var url = $("#music-url").val();
    const encoded_url = encodeURIComponent(url);
    $.get(`/playurl?url=${encoded_url}&did=${did}`, function(data, status) {
      console.log(data);
    });
  });

  function append_op_button_name(name) {
    append_op_button(null, name, name);
  }

  function append_op_button(id, name, cmd) {
    // 创建按钮
    const $button = $("<button>");
    $button.text(name);
    $button.attr("type", "button");
    if (id !== null) {
      $button.attr("id", id);
    }

    // 设置按钮点击事件
    $button.on("click", () => {
      sendcmd(cmd);
    });

    // 添加按钮到容器
    $container.append($button);
  }

  function do_play_music(musicname, searchkey) {
    $.ajax({
      type: "POST",
      url: "/playmusic",
      contentType: "application/json; charset=utf-8",
      data: JSON.stringify({did: did, musicname: musicname, searchkey: searchkey}),
      success: () => {
        console.log("do_play_music succ", musicname, searchkey);
      },
      error: () => {
        console.log("do_play_music failed", musicname, searchkey);
      }
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

  $("#volume").on('change', function () {
    var value = $(this).val();
    $.ajax({
      type: "POST",
      url: "/setvolume",
      contentType: "application/json; charset=utf-8",
      data: JSON.stringify({did: did, volume: value}),
      success: () => {
      },
      error: () => {
      }
    });
  });

  function check_status_refresh_music_list(retries) {
    $.get("/cmdstatus", function(data) {
      if (data.status === "finish") {
        refresh_music_list();
      } else if (retries > 0) {
        setTimeout(function() {
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
      data: JSON.stringify({did: did, cmd: cmd}),
      success: () => {
        if (cmd == "刷新列表") {
          check_status_refresh_music_list(3); // 最多重试3次
        }
        if (["全部循环", "单曲循环", "随机播放", "单曲播放", "顺序播放"].includes(cmd)) {
          location.reload();
        }
      },
      error: () => {
        // 请求失败时执行的操作
      }
    });
  }

	// 监听输入框的输入事件
  function debounce(func, delay) {
		let timeout;
		return function(...args) {
			clearTimeout(timeout);
			timeout = setTimeout(() => func.apply(this, args), delay);
		};
	}

  const searchInput = document.getElementById('search');
  const musicSelect = document.getElementById('music-name');
  const musicSelectLabel = document.getElementById('music-name-label');

  searchInput.addEventListener('input', debounce(function() {
    const query = searchInput.value.trim();

    if (query.length === 0) {
      musicSelect.innerHTML = '';
      musicSelect.style.display = 'none'
      musicSelectLabel.style.display = 'none'
      return;
    }

    musicSelect.style.display = 'block'
    musicSelectLabel.style.display = 'block'
    fetch(`/searchmusic?name=${encodeURIComponent(query)}`)
      .then(response => response.json())
      .then(data => {
        musicSelect.innerHTML = ''; // 清空现有选项

        // 找到的优先显示
        if (data.length > 0) {
          data.forEach(song => {
            const option = document.createElement('option');
            option.value = song
            option.textContent = song
            musicSelect.appendChild(option);
          });
        }

        // 添加用户输入作为一个选项
        const userOption = document.createElement('option');
        userOption.value = query;
        userOption.textContent = `使用关键词播放: ${query}`;
        musicSelect.appendChild(userOption);

        // 提示没找到
        if (data.length === 0) {
          const option = document.createElement('option');
          option.textContent = '没有匹配的结果';
          option.disabled = true;
          musicSelect.appendChild(option);
        }
      })
      .catch(error => {
          console.error('Error fetching data:', error);
      });
  }, 500));

  // 动态显示保存文件名输入框
  const musicNameSelect = document.getElementById('music-name');
  const musicFilenameInput = document.getElementById('music-filename');
  function updateInputVisibility() {
    const selectedOption = musicNameSelect.options[musicNameSelect.selectedIndex];
    var startsWithKeyword;
    if (musicNameSelect.options.length === 0) {
      startsWithKeyword = false;
    } else {
      startsWithKeyword = selectedOption.text.startsWith("使用关键词播放:");
    }
    
    if (startsWithKeyword) {
      musicFilenameInput.style.display = 'block';
      musicFilenameInput.placeholder = '请输入保存为的文件名称(默认:' + selectedOption.value + ')';
    } else {
      musicFilenameInput.style.display = 'none';
    }
  }
  // 观察元素修改
  const observer = new MutationObserver((mutationsList) => {
    for (const mutation of mutationsList) {
      if (mutation.type === 'childList') {
        updateInputVisibility()
      }
    }
  });
  observer.observe(musicNameSelect, { childList: true });
  // 监听用户输入
  musicNameSelect.addEventListener('change', updateInputVisibility);

  function get_playing_music() {
    $.get(`/playingmusic?did=${did}`, function(data, status) {
      console.log(data);
      if (data.ret == "OK") {
        if (data.is_playing) {
          $("#playering-music").text(`【播放中】 ${data.cur_music}`);
        } else {
          $("#playering-music").text(`【空闲中】 ${data.cur_music}`);
        }
        offset = data.offset;
        duration = data.duration;
      }
    });
  }
  setInterval(()=>{
      if (duration > 0) {
        offset++;
        $("#progress").val(offset / duration * 100);
        $("#play-time").text(`${formatTime(offset)}/${formatTime(duration)}`)
      }else{
        $("#play-time").text(`${formatTime(0)}/${formatTime(0)}`)
      }
    },1000)
  function formatTime(seconds) {
    var minutes = Math.floor(seconds / 60);
    var remainingSeconds =Math.floor(seconds % 60);
    return `${minutes.toString().padStart(2, '0')}:${remainingSeconds.toString().padStart(2, '0')}`;
  }
  
  $("audio").on("error", (e) => {
    //如果audio标签的src为空，则不做任何操作，兼容安卓端的低版本webview
    if ($("audio").attr("src") === "") {
      return;
    }
    console.log('%c网页播放出现错误: ', 'color: #007acc;', e.currentTarget.error.code,e.currentTarget.error.message);
    alert(e.currentTarget.error.code==4 ? "无法打开媒体文件，XIAOMUSIC_HOSTNAME或端口地址错误，请重新设置" : "在线播放失败，请截图反馈: "+e.currentTarget.error.message);
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

      localStorage.setItem('no-warning', 'true');
      // 设置全局变量
      no_warning = true;
      return true;
    }
      // 如果当前页面的Host与设置中的XIAOMUSIC_HOSTNAME、PORT不一致
      const validHost = document.getElementById('valid-host');
      let validFlag = false;
      $('#local-host').text(local);
      $('#setting-host').text(host);
      validHost.showModal();
      //监听validHost的close事件
      function _handleClose() {
        console.log('%c提醒HOST不一致弹窗,用户已选择: ', 'color: #007acc;', validHost.returnValue);
        if (validHost.returnValue == "no-warning") {
          localStorage.setItem('no-warning', 'true');
          no_warning = true;
          validFlag = true;
        }
        validHost.removeEventListener('close', _handleClose)
      }
      validHost.addEventListener('close', _handleClose)
      return validFlag; 
  }
});

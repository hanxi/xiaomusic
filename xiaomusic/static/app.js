$(function(){
  $container=$("#cmds");
  append_op_button_name("全部循环");
  append_op_button_name("单曲循环");
  append_op_button_name("随机播放");
  append_op_button_name("刷新列表");
  append_op_button_name("下一首");
  append_op_button_name("关机");

  $container.append($("<hr>"));

  append_op_button_name("10分钟后关机");
  append_op_button_name("30分钟后关机");
  append_op_button_name("60分钟后关机");

  // 拉取声音
  sendcmd("get_volume#");
  $.get("/getvolume", function(data, status) {
    console.log(data, status, data["volume"]);
    $("#volume").val(data.volume);
  });

  // 拉取版本
  $.get("/getversion", function(data, status) {
    console.log(data, status, data["version"]);
    $("#version").text(`(${data.version})`);
  });

  // 拉取播放列表
  function refresh_music_list() {
    $('#music_list').empty();
    $.get("/musiclist", function(data, status) {
      console.log(data, status);
      $.each(data, function(key, value) {
        $('#music_list').append($('<option></option>').val(key).text(key));
      });

      $('#music_list').change(function() {
        const selectedValue = $(this).val();
        $('#music_name').empty();
        const sorted_musics = data[selectedValue].sort(custom_sort_key);
        $.each(sorted_musics, function(index, item) {
          $('#music_name').append($('<option></option>').val(item).text(item));
        });
      });

      $('#music_list').trigger('change');

      // 获取当前播放列表
      $.get("curplaylist", function(data, status) {
        $('#music_list').val(data);
        $('#music_list').trigger('change');
      })
    })
  }
  refresh_music_list();

  $("#play_music_list").on("click", () => {
    var music_list = $("#music_list").val();
    var music_name = $("#music_name").val();
    let cmd = "播放列表" + music_list + "|" + music_name;
    sendcmd(cmd);
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

  function append_op_button_name(name) {
    append_op_button(name, name);
  }

  function append_op_button(name, cmd) {
    // 创建按钮
    const $button = $("<button>");
    $button.text(name);
    $button.attr("type", "button");

    // 设置按钮点击事件
    $button.on("click", () => {
      sendcmd(cmd);
    });

    // 添加按钮到容器
    $container.append($button);
  }

  $("#play").on("click", () => {
    var search_key = $("#music-name").val();
    var filename = $("#music-filename").val();
    let cmd = "播放歌曲" + search_key + "|" + filename;
    sendcmd(cmd);
  });

  $("#volume").on('input', function () {
    var value = $(this).val();
    sendcmd("set_volume#"+value);
  });

  function sendcmd(cmd) {
    $.ajax({
      type: "POST",
      url: "/cmd",
      contentType: "application/json; charset=utf-8",
      data: JSON.stringify({cmd: cmd}),
      success: () => {
        if (cmd == "刷新列表") {
          setTimeout(refresh_music_list, 3000);
        }
      },
      error: () => {
        // 请求失败时执行的操作
      }
    });
  }

  // 监听输入框的输入事件
  $("#music-name").on('input', function() {
    var inputValue = $(this).val();
    // 发送Ajax请求
    $.ajax({
      url: "searchmusic", // 服务器端处理脚本
      type: "GET",
      dataType: "json",
      data: {
        name: inputValue
      },
      success: function(data) {
        // 清空datalist
        $("#autocomplete-list").empty();
        // 添加新的option元素
        $.each(data, function(i, item) {
          $('<option>').val(item).appendTo("#autocomplete-list");
        });
      }
    });
  });

  function get_playing_music() {
    $.get("/playingmusic", function(data, status) {
      console.log(data);
      $("#playering-music").text(data);
    });
  }

  // 每3秒获取下正在播放的音乐
  get_playing_music();
  setInterval(() => {
    get_playing_music();
  }, 3000);

  function custom_sort_key(a, b) {
    // 使用正则表达式提取数字前缀
    const numericPrefixA = a.match(/^(\d+)/) ? parseInt(a.match(/^(\d+)/)[1], 10) : null;
    const numericPrefixB = b.match(/^(\d+)/) ? parseInt(b.match(/^(\d+)/)[1], 10) : null;

    // 如果两个键都有数字前缀，则按数字大小排序
    if (numericPrefixA !== null && numericPrefixB !== null) {
      return numericPrefixA - numericPrefixB;
    }

    // 如果一个键有数字前缀而另一个没有，则有数字前缀的键排在前面
    if (numericPrefixA !== null) return -1;
    if (numericPrefixB !== null) return 1;

    // 如果两个键都没有数字前缀，则按照常规字符串排序
    return a.localeCompare(b);
  }

});

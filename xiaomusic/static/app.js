$(function(){
  // 拉取所有可操作的命令
  $.get("/allcmds", function(data, status) {
    console.log(data, status);

    $container=$("#cmds");
    // 遍历数据
    for (const [key, value] of Object.entries(data)) {
      if (key != "分钟后关机"
        && key != "放歌曲"
        && key != "停止播放"
        && !key.includes("#")) {
        append_op_button_name(key);
      }
    }

    $container.append($("<hr>"));
    append_op_button_name("10分钟后关机");
    append_op_button_name("30分钟后关机");
    append_op_button_name("60分钟后关机");

    $container.append($("<hr>"));
    append_op_button_volume("声音设为5", 5);
    append_op_button_volume("声音设为10", 10);
    append_op_button_volume("声音设为30", 30);
    append_op_button_volume("声音设为50", 50);
    append_op_button_volume("声音设为80", 80);
    append_op_button_volume("声音设为100", 100);
  });

  function append_op_button_volume(name, value) {
    append_op_button(name, "set_volume#"+value);
  }
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
        // 发起post请求
        $.ajax({
          type: "POST",
          url: "/cmd",
          contentType: "application/json",
          data: JSON.stringify({"cmd": cmd}),
          success: () => {
            // 请求成功时执行的操作
          },
          error: () => {
            // 请求失败时执行的操作
          }
        });
      });

      // 添加按钮到容器
      $container.append($button);
  }

  $("#play").on("click", () => {
    name = $("#music-name").val();
    let cmd = "播放歌曲"+name;
    $.ajax({
      type: "POST",
      url: "/cmd",
      contentType: "application/json",
      data: JSON.stringify({cmd: cmd}),
      success: () => {
        // 请求成功时执行的操作
      },
      error: () => {
        // 请求失败时执行的操作
      }
    });
  });
});

$(function(){
  // 拉取所有可操作的命令
  $.get("/allcmds", function(data, status) {
    console.log(data, status);

    $container=$("#cmds");
    // 遍历数据
    for (const [key, value] of Object.entries(data)) {
      if (key != "分钟后关机" && key != "放歌曲") {
        append_op_button(key);
      }
    }

    append_op_button("5分钟后关机");
    append_op_button("10分钟后关机");
    append_op_button("30分钟后关机");
    append_op_button("60分钟后关机");
  });

  function append_op_button(name) {
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
          data: JSON.stringify({cmd: name}),
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

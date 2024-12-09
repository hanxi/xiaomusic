$(function(){
  // 拉取版本
  $.get("/getversion", function(data, status) {
    console.log(data, status, data["version"]);
    $("#version").text(`${data.version}`);
  });

  // 遍历所有的select元素，默认选中只有1个选项的
  const autoSelectOne = () => {
    $('select').each(function() {
      // 如果select元素仅有一个option子元素
      if ($(this).children('option').length === 1) {
        // 选中这个option
        $(this).find('option').prop('selected', true);
      }
    });
  };

  function updateCheckbox(selector, mi_did, device_list,accountPassValid) {
    // 清除现有的内容
    $(selector).empty();

    // 将 mi_did 字符串通过逗号分割转换为数组，以便于判断默认选中项
    var selected_dids = mi_did.split(',');

    //如果device_list为空，则可能是未设置小米账号密码或者已设置密码，但是没有过小米验证，此处需要提示用户
    if (device_list.length == 0) {
      const loginTips = accountPassValid ? `<div class="login-tips">未发现可用的小爱设备，请检查账号密码是否输错，并关闭加速代理或在<a href="https://www.mi.com">小米官网</a>登陆过人脸或滑块验证。如仍未解决。请根据<a href="https://github.com/hanxi/xiaomusic/issues/99">FAQ</a>的内容解决问题。</div>` : `<div class="login-tips">未发现可用的小爱设备，请先在下面的输入框中设置小米的<b>账号、密码</b></div>`;
      $(selector).append(loginTips);
      return;
    }
    $.each(device_list, function(index, device) {
      var did = device.miotDID;
      var hardware = device.hardware;
      var name = device.name;
      // 创建复选框元素
      var checkbox = $('<input>', {
        type: 'checkbox',
        id: did,
        value: `${did}`,
        class: 'custom-checkbox', // 添加样式类
        // 如果mi_did中包含了该did，则默认选中
        checked: selected_dids.indexOf(did) !== -1
      });

      // 创建标签元素
      var label = $('<label>', {
        for: did,
        class: 'checkbox-label', // 添加样式类
        text: `【${hardware} ${did}】${name}` // 设定标签内容
      });

      // 将复选框和标签添加到目标选择器元素中
      $(selector).append(checkbox).append(label);
    });
  }

  function getSelectedDids(containerSelector) {
    var selectedDids = [];

    // 仅选择给定容器中选中的复选框
    $(containerSelector + ' .custom-checkbox:checked').each(function() {
      var did = this.value;
      selectedDids.push(did);
    });

    return selectedDids.join(',');
  }

  // 拉取现有配置
  $.get("/getsetting?need_device_list=true", function(data, status) {
    console.log(data, status);
    const accountPassValid = data.account && data.password;
    updateCheckbox("#mi_did", data.mi_did, data.device_list, accountPassValid);

    // 初始化显示
    for (const key in data) {
        const $element = $("#" + key);
        if ($element.length) {
          if (data[key] === true) {
            $element.val('true');
          } else if (data[key] === false) {
            $element.val('false');
          } else {
            $element.val(data[key]);
          }
        }
    }

    autoSelectOne();
  });

  $(".save-button").on("click", () => {
    var setting = $('#setting');
    var inputs = setting.find('input, select, textarea');
    var data = {};
    inputs.each(function() {
      var id = this.id;
      if (id) {
        data[id] = $(this).val();
      }
    });
    var did_list = getSelectedDids("#mi_did");
    data["mi_did"] = did_list;
    console.log(data)

    $.ajax({
      type: "POST",
      url: "/savesetting",
      contentType: "application/json",
      data: JSON.stringify(data),
      success: (msg) => {
        alert(msg);
        location.reload();
      },
      error: (msg) => {
        alert(msg);
      }
    });
  });

  $("#get_music_list").on("click", () => {
    var music_list_url = $("#music_list_url").val();
    console.log("music_list_url", music_list_url);
    var data = {
      url: music_list_url,
    };
    $.ajax({
      type: "POST",
      url: "/downloadjson",
      contentType: "application/json",
      data: JSON.stringify(data),
      success: (res) => {
        if (res.ret == "OK") {
          $("#music_list_json").val(res.content);
        } else {
          console.log(res);
          alert(res.ret);
        }
      },
      error: (res) => {
        console.log(res);
        alert(res);
      }
    });
  });

  $("#refresh_music_tag").on("click", () => {
    $.ajax({
      type: "POST",
      url: "/refreshmusictag",
      contentType: "application/json",
      success: (res) => {
        console.log(res);
        alert(res.ret);
      },
      error: (res) => {
        console.log(res);
        alert(res);
      }
    });
  });

  $("#upload_yt_dlp_cookie").on("click", () => {
    var fileInput = document.getElementById('yt_dlp_cookies_file');
    var file = fileInput.files[0]; // 获取文件对象
    if (file) {
      var formData = new FormData();
      formData.append("file", file);
      $.ajax({
        url: "/uploadytdlpcookie",
        type: "POST",
        data: formData,
        processData: false,
        contentType: false,
        success: function(res) {
          console.log(res);
          alert("上传成功");
        },
        error: function(jqXHR, textStatus, errorThrown) {
          console.log(res);
          alert("上传失败");
        }
      });
    } else {
        alert("请选择一个文件");
    }
  });


  $("#clear_cache").on("click", () => {
    localStorage.clear();
  });
  $("#hostname").on("change", function(){
    const hostname = $(this).val();
    // 检查是否包含端口号（1到5位数字）
    if (hostname.match(/:\d{1,5}$/)) {
      alert("hostname禁止带端口号");
      // 移除端口号
      $(this).val(hostname.replace(/:\d{1,5}$/,""));
    }
  });
});

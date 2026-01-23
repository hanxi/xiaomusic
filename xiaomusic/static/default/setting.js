// ============ 字体加载检测 ============
// 检测字体加载完成，避免图标文字闪烁
(function() {
  // 使用 Promise.race 实现超时保护
  const fontLoadTimeout = new Promise(resolve => {
    setTimeout(() => {
      console.warn('字体加载超时，强制显示图标');
      resolve('timeout');
    }, 3000);
  });

  const fontLoadReady = document.fonts.ready.then(() => 'loaded');

  Promise.race([fontLoadReady, fontLoadTimeout]).then((result) => {
    document.body.classList.add('fonts-loaded');
    if (result === 'loaded') {
      console.log('Material Icons 字体加载完成');
    }
  }).catch((error) => {
    console.error('字体加载检测失败:', error);
    // 出错时也显示图标，避免永久隐藏
    document.body.classList.add('fonts-loaded');
  });
})();

$(function () {
  // 拉取版本
  $.get("/getversion", function (data, status) {
    console.log(data, status, data["version"]);
    $("#version").text(`${data.version}`);
  });

  // 遍历所有的select元素，默认选中只有1个选项的
  const autoSelectOne = () => {
    $("select").each(function () {
      // 如果select元素仅有一个option子元素
      if ($(this).children("option").length === 1) {
        // 选中这个option
        $(this).find("option").prop("selected", true);
      }
    });
  };

  function updateCheckbox(selector, mi_did, device_list, accountPassValid) {
    // 清除现有的内容
    $(selector).empty();

    // 将 mi_did 字符串通过逗号分割转换为数组，以便于判断默认选中项
    var selected_dids = mi_did.split(",");

    //如果device_list为空，则可能是未设置小米账号密码或者已设置密码，但是没有过小米验证，此处需要提示用户
    if (device_list.length == 0) {
      const loginTips = accountPassValid
        ? `<div class="login-tips">未发现可用的小爱设备，请检查账号密码是否输错，并关闭加速代理或在<a href="https://www.mi.com">小米官网</a>登陆过人脸或滑块验证。如仍未解决。请根据<a href="https://github.com/hanxi/xiaomusic/issues/99">FAQ</a>的内容解决问题。</div>`
        : `<div class="login-tips">未发现可用的小爱设备，请先在下面的输入框中设置小米的<b>账号、密码或者cookie</b></div>`;
      $(selector).append(loginTips);
      return;
    }
    $.each(device_list, function (index, device) {
      var did = device.miotDID;
      var hardware = device.hardware;
      var name = device.name;
      // 创建复选框元素
      var checkbox = $("<input>", {
        type: "checkbox",
        id: did,
        value: `${did}`,
        class: "custom-checkbox", // 添加样式类
        // 如果mi_did中包含了该did，则默认选中
        checked: selected_dids.indexOf(did) !== -1,
      });

      // 创建标签元素
      var label = $("<label>", {
        for: did,
        class: "checkbox-label", // 添加样式类
        text: `【${hardware} ${did}】${name}`, // 设定标签内容
      });

      // 将复选框和标签添加到目标选择器元素中
      $(selector).append(checkbox).append(label);
    });
  }

  function getSelectedDids(containerSelector) {
    var selectedDids = [];

    // 仅选择给定容器中选中的复选框
    $(containerSelector + " .custom-checkbox:checked").each(function () {
      var did = this.value;
      selectedDids.push(did);
    });

    return selectedDids.join(",");
  }

  // 拉取现有配置
  $.get("/getsetting?need_device_list=true", function (data, status) {
    console.log(data, status);
    const accountPassValid = data.account && data.password;
    updateCheckbox("#mi_did", data.mi_did, data.device_list, accountPassValid);

    // 初始化显示
    for (const key in data) {
      const $element = $("#" + key);
      if ($element.length) {
        if (data[key] === true) {
          $element.val("true");
        } else if (data[key] === false) {
          $element.val("false");
        } else {
          $element.val(data[key]);
        }
      }
    }

    autoSelectOne();
  });

  $(".save-button").on("click", () => {
    var setting = $("#setting");
    var inputs = setting.find("input, select, textarea");
    var data = {};
    inputs.each(function () {
      var id = this.id;
      if (id) {
        data[id] = $(this).val();
      }
    });
    var did_list = getSelectedDids("#mi_did");
    data["mi_did"] = did_list;
    console.log(data);

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
      },
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
      },
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
      },
    });
  });

  $("#upload_yt_dlp_cookie").on("click", () => {
    var fileInput = document.getElementById("yt_dlp_cookies_file");
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
        success: function (res) {
          console.log(res);
          alert("上传成功");
        },
        error: function (jqXHR, textStatus, errorThrown) {
          console.log(res);
          alert("上传失败");
        },
      });
    } else {
      alert("请选择一个文件");
    }
  });

  $("#clear_cache").on("click", () => {
    localStorage.clear();
    alert("清除成功");
  });

  $("#cleantempdir").on("click", () => {
    $.ajax({
      type: "POST",
      url: "/api/file/cleantempdir",
      contentType: "application/json",
      data: JSON.stringify({}),
      success: (msg) => {
        alert(msg.ret);
      },
      error: (msg) => {
        alert(msg);
      },
    });
  });

  $("#hostname").on("change", function () {
    const hostname = $(this).val();
    // 检查是否包含端口号（1到5位数字）
    if (hostname.match(/:\d{1,5}$/)) {
      alert("hostname禁止带端口号");
      // 移除端口号
      $(this).val(hostname.replace(/:\d{1,5}$/, ""));
    }
  });

  $("#auto-hostname").on("click", () => {
    const protocol = window.location.protocol;
    const hostname = window.location.hostname;
    if (hostname == "127.0.0.1" || hostname == "localhost") {
      alert("hostname 不能是 127.0.0.1 或者 localhost");
    }
    const baseUrl = `${protocol}//${hostname}`;
    console.log(baseUrl);
    $("#hostname").val(baseUrl);
  });

  $("#auto-port").on("click", () => {
    const port = window.location.port;
    if (port == 0) {
      const protocol = window.location.protocol;
      if (protocol == "https:") {
        port = 443;
      } else {
        port = 80;
      }
    }
    console.log(port);
    $("#public_port").val(port);
  });

  // 高级配置折叠功能
  const toggleBtn = $("#advancedConfigToggle");
  const content = $("#advancedConfigContent");

  // 从localStorage读取折叠状态，默认折叠
  const isCollapsed =
    localStorage.getItem("advancedConfigCollapsed") !== "false";

  // 初始化状态
  if (isCollapsed) {
    toggleBtn.addClass("collapsed");
    content.addClass("collapsed");
  }

  // 点击切换折叠状态
  toggleBtn.on("click", function () {
    const willCollapse = !toggleBtn.hasClass("collapsed");

    if (willCollapse) {
      toggleBtn.addClass("collapsed");
      content.addClass("collapsed");
      localStorage.setItem("advancedConfigCollapsed", "true");
    } else {
      toggleBtn.removeClass("collapsed");
      content.removeClass("collapsed");
      localStorage.setItem("advancedConfigCollapsed", "false");
    }
  });

  // Tab 切换功能
  $(".auth-tab-button").on("click", function () {
    const tabName = $(this).data("tab");

    // 移除所有 active 类
    $(".auth-tab-button").removeClass("active");
    $(".auth-tab-content").removeClass("active");

    // 添加当前 active 类
    $(this).addClass("active");
    $("#tab-" + tabName).addClass("active");
  });

  // 功能操作区域折叠功能
  const operationToggle = $("#operationToggle");
  const operationContent = $("#operationContent");

  // 从localStorage读取折叠状态，默认折叠
  const operationCollapsedState = localStorage.getItem("operationCollapsed");
  const isOperationCollapsed =
    operationCollapsedState === null || operationCollapsedState === "true";

  // 初始化状态
  if (!isOperationCollapsed) {
    // 如果用户之前展开过，则移除 collapsed 类
    operationToggle.removeClass("collapsed");
    operationContent.removeClass("collapsed");
  }

  // 点击切换折叠状态
  operationToggle.on("click", function () {
    const willCollapse = !operationToggle.hasClass("collapsed");

    if (willCollapse) {
      operationToggle.addClass("collapsed");
      operationContent.addClass("collapsed");
      localStorage.setItem("operationCollapsed", "true");
    } else {
      operationToggle.removeClass("collapsed");
      operationContent.removeClass("collapsed");
      localStorage.setItem("operationCollapsed", "false");
    }
  });

  // 工具链接区域折叠功能
  const toolsToggle = $("#toolsToggle");
  const toolsContent = $("#toolsContent");

  // 从localStorage读取折叠状态，默认折叠
  const toolsCollapsedState = localStorage.getItem("toolsCollapsed");
  const isToolsCollapsed =
    toolsCollapsedState === null || toolsCollapsedState === "true";

  // 初始化状态
  if (!isToolsCollapsed) {
    // 如果用户之前展开过，则移除 collapsed 类
    toolsToggle.removeClass("collapsed");
    toolsContent.removeClass("collapsed");
  }

  // 点击切换折叠状态
  toolsToggle.on("click", function () {
    const willCollapse = !toolsToggle.hasClass("collapsed");

    if (willCollapse) {
      toolsToggle.addClass("collapsed");
      toolsContent.addClass("collapsed");
      localStorage.setItem("toolsCollapsed", "true");
    } else {
      toolsToggle.removeClass("collapsed");
      toolsContent.removeClass("collapsed");
      localStorage.setItem("toolsCollapsed", "false");
    }
  });

  // ============ 无障碍功能 ============

  // Tab 切换功能增强
  const tabButtons = $(".auth-tab-button");
  const tabPanels = $(".auth-tab-content");

  // Tab 切换函数
  function switchTab(index) {
    // 更新按钮状态
    tabButtons.removeClass("active").attr("aria-selected", "false");
    $(tabButtons[index]).addClass("active").attr("aria-selected", "true");

    // 更新面板显示
    tabPanels.removeClass("active");
    $(tabPanels[index]).addClass("active");

    // 移动焦点到激活的 Tab
    tabButtons[index].focus();
  }

  // Tab 按钮点击事件
  tabButtons.on("click", function () {
    const index = tabButtons.index(this);
    switchTab(index);
  });

  // Tab 键盘导航
  tabButtons.on("keydown", function (e) {
    const currentIndex = tabButtons.index(this);
    let newIndex = currentIndex;

    switch (e.key) {
      case "ArrowLeft":
        // 左箭头 - 前一个 Tab
        newIndex = currentIndex > 0 ? currentIndex - 1 : tabButtons.length - 1;
        e.preventDefault();
        break;
      case "ArrowRight":
        // 右箭头 - 下一个 Tab
        newIndex = currentIndex < tabButtons.length - 1 ? currentIndex + 1 : 0;
        e.preventDefault();
        break;
      case "Home":
        // Home 键 - 第一个 Tab
        newIndex = 0;
        e.preventDefault();
        break;
      case "End":
        // End 键 - 最后一个 Tab
        newIndex = tabButtons.length - 1;
        e.preventDefault();
        break;
      default:
        return;
    }

    if (newIndex !== currentIndex) {
      switchTab(newIndex);
    }
  });

  // 高级配置折叠按钮的 ARIA 更新
  function updateAdvancedConfigAria() {
    const isExpanded = !toggleBtn.hasClass("collapsed");
    toggleBtn.attr("aria-expanded", isExpanded ? "true" : "false");
  }

  // 初始化 ARIA 状态
  updateAdvancedConfigAria();

  // 修改高级配置折叠点击事件，添加 ARIA 更新
  toggleBtn.off("click").on("click", function () {
    const willCollapse = !toggleBtn.hasClass("collapsed");

    if (willCollapse) {
      toggleBtn.addClass("collapsed");
      content.addClass("collapsed");
      localStorage.setItem("advancedCollapsed", "true");
    } else {
      toggleBtn.removeClass("collapsed");
      content.removeClass("collapsed");
      localStorage.setItem("advancedCollapsed", "false");
    }

    // 更新 ARIA 属性
    updateAdvancedConfigAria();
  });

  // 高级配置折叠按钮的键盘支持
  toggleBtn.on("keydown", function (e) {
    if (e.key === "Enter" || e.key === " ") {
      $(this).click();
      e.preventDefault();
    }
  });

  // 工具折叠按钮的 ARIA 更新
  function updateToolsAria() {
    const isExpanded = !toolsToggle.hasClass("collapsed");
    toolsToggle.attr("aria-expanded", isExpanded ? "true" : "false");
  }

  // 初始化工具折叠的 ARIA 状态
  if (typeof toolsToggle !== "undefined" && toolsToggle.length > 0) {
    updateToolsAria();

    // 修改工具折叠点击事件，添加 ARIA 更新
    toolsToggle.off("click").on("click", function () {
      const willCollapse = !toolsToggle.hasClass("collapsed");

      if (willCollapse) {
        toolsToggle.addClass("collapsed");
        toolsContent.addClass("collapsed");
        localStorage.setItem("toolsCollapsed", "true");
      } else {
        toolsToggle.removeClass("collapsed");
        toolsContent.removeClass("collapsed");
        localStorage.setItem("toolsCollapsed", "false");
      }

      // 更新 ARIA 属性
      updateToolsAria();
    });

    // 工具折叠按钮的键盘支持
    toolsToggle.on("keydown", function (e) {
      if (e.key === "Enter" || e.key === " ") {
        $(this).click();
        e.preventDefault();
      }
    });
  }

  // 为所有自定义按钮添加键盘支持
  $('[role="button"]').on("keydown", function (e) {
    if (e.key === "Enter" || e.key === " ") {
      $(this).click();
      e.preventDefault();
    }
  });
});

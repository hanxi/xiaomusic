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

  function updateCheckbox(selector, mi_did_list, mi_did, mi_hardware_list) {
    // 清除现有的内容
    $(selector).empty();

    // 将 mi_did 字符串通过逗号分割转换为数组，以便于判断默认选中项
    var selected_dids = mi_did.split(',');

    // 遍历传入的 mi_did_list 和 mi_hardware_list
    $.each(mi_did_list, function(index, did) {
      // 获取硬件标识，假定列表是一一对应的
      var hardware = mi_hardware_list[index];

      // 创建复选框元素
      var checkbox = $('<input>', {
        type: 'checkbox',
        id: did,
        value: `${did}|${hardware}`,
        class: 'custom-checkbox', // 添加样式类
        // 如果mi_did中包含了该did，则默认选中
        checked: selected_dids.indexOf(did) !== -1
      });

      // 创建标签元素
      var label = $('<label>', {
        for: did,
        class: 'checkbox-label', // 添加样式类
        text: `【${hardware}】 ${did}` // 设定标签内容为did和hardware的拼接
      });

      // 将复选框和标签添加到目标选择器元素中
      $(selector).append(checkbox).append(label);
    });
  }

  function getSelectedDidsAndHardware(containerSelector) {
    var selectedDids = [];
    var selectedHardware = [];

    // 仅选择给定容器中选中的复选框
    $(containerSelector + ' .custom-checkbox:checked').each(function() {
      // 解析当前复选框的值（值中包含了 did 和 hardware，使用 '|' 分割）
      var parts = this.value.split('|');
      selectedDids.push(parts[0]);
      selectedHardware.push(parts[1]);
    });

    // 返回包含 did_list 和 hardware_list 的对象
    return {
      did_list: selectedDids.join(','),
      hardware_list: selectedHardware.join(',')
    };
  }

  // 拉取现有配置
  $.get("/getsetting", function(data, status) {
    console.log(data, status);
    updateCheckbox("#mi_did_hardware", data.mi_did_list, data.mi_did, data.mi_hardware_list);

    // 初始化显示
    for (const key in data) {
      if (data.hasOwnProperty(key)) {
        const $element = $("#" + key);
        if ($element.length && data[key] !== '') {
          if (data[key] === true) {
            $element.val('true');
          } else if (data[key] === false) {
            $element.val('false');
          } else {
            $element.val(data[key]);
          }
        }
      }
    }

    autoSelectOne();
  });

  $("#save").on("click", () => {
    var setting = $('#setting');
    var inputs = setting.find('input, select, textarea');
    var data = {};
    inputs.each(function() {
      var id = this.id;
      if (id) {
        data[id] = $(this).val();
      }
    });
    var selectedData = getSelectedDidsAndHardware("#mi_did_hardware");
    data["mi_did"] = selectedData.did_list;
    data["hardware"] = selectedData.hardware_list;
    console.log(data)

    $.ajax({
      type: "POST",
      url: "/savesetting",
      contentType: "application/json",
      data: JSON.stringify(data),
      success: (msg) => {
        alert(msg);
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
});

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

  const updateSelectOptions = (selectId, optionsList, selectedOption) => {
    const select = $(selectId);
    select.empty();
    optionsList.forEach(option => {
      select.append(new Option(option, option));
    });
    select.val(selectedOption);
  };

  let isChanging = false;
  // 更新下拉菜单的函数
  const updateSelect = (selectId, value) => {
    if (!isChanging) {
      isChanging = true;
      $(selectId).val(value);
      isChanging = false;
    }
  };

  // 联动逻辑
  const linkSelects = (sourceSelect, sourceList, targetSelect, targetList) => {
    $(sourceSelect).change(function() {
      if (!isChanging) {
        const selectedValue = $(this).val();
        const selectedIndex = sourceList.indexOf(selectedValue);
        console.log(selectedIndex, selectedValue,sourceList,targetList)
        if (selectedIndex !== -1) {
          updateSelect(targetSelect, targetList[selectedIndex]);
        }
      }
    });
  };


  // 拉取现有配置
  $.get("/getsetting", function(data, status) {
    console.log(data, status);
    updateSelectOptions("#mi_did", data.mi_did_list, data.mi_did);
    updateSelectOptions("#hardware", data.mi_hardware_list, data.hardware);

    // 初始化联动
    linkSelects('#mi_did', data.mi_did_list, '#hardware', data.mi_hardware_list);

    // 初始化显示
    for (const key in data) {
      if (data.hasOwnProperty(key) && data[key] != "") {
        const $element = $("#" + key);
        if ($element.length) {
          $element.val(data[key]);
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

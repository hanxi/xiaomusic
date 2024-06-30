$(function(){
  // 拉取版本
  $.get("/getversion", function(data, status) {
    console.log(data, status, data["version"]);
    $("#version").text(`${data.version}`);
  });

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
    updateSelectOptions("#mi_hardware", data.mi_hardware_list, data.mi_hardware);

    // 初始化联动
    linkSelects('#mi_did', data.mi_did_list, '#mi_hardware', data.mi_hardware_list);

    if (data.xiaomusic_search != "") {
      $("#xiaomusic_search").val(data.xiaomusic_search);
    }

    if (data.xiaomusic_proxy != "") {
      $("#xiaomusic_proxy").val(data.xiaomusic_proxy);
    }

    if (data.xiaomusic_music_list_url != "") {
      $("#xiaomusic_music_list_url").val(data.xiaomusic_music_list_url);
    }

    if (data.xiaomusic_music_list_json != "") {
      $("#xiaomusic_music_list_json").val(data.xiaomusic_music_list_json);
    }
  });

  $("#save").on("click", () => {
    var mi_did = $("#mi_did").val();
    var mi_hardware = $("#mi_hardware").val();
    var xiaomusic_search = $("#xiaomusic_search").val();
    var xiaomusic_proxy = $("#xiaomusic_proxy").val();
    var xiaomusic_music_list_url = $("#xiaomusic_music_list_url").val();
    var xiaomusic_music_list_json = $("#xiaomusic_music_list_json").val();
    console.log("mi_did", mi_did);
    console.log("mi_hardware", mi_hardware);
    console.log("xiaomusic_search", xiaomusic_search);
    console.log("xiaomusic_proxy", xiaomusic_proxy);
    console.log("xiaomusic_music_list_url", xiaomusic_music_list_url);
    console.log("xiaomusic_music_list_json", xiaomusic_music_list_json);
    var data = {
      mi_did: mi_did,
      mi_hardware: mi_hardware,
      xiaomusic_search: xiaomusic_search,
      xiaomusic_proxy: xiaomusic_proxy,
      xiaomusic_music_list_url: xiaomusic_music_list_url,
      xiaomusic_music_list_json: xiaomusic_music_list_json,
    };
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
    var xiaomusic_music_list_url = $("#xiaomusic_music_list_url").val();
    console.log("xiaomusic_music_list_url", xiaomusic_music_list_url);
    var data = {
      url: xiaomusic_music_list_url,
    };
    $.ajax({
      type: "POST",
      url: "/downloadjson",
      contentType: "application/json",
      data: JSON.stringify(data),
      success: (res) => {
        if (res.ret == "OK") {
          $("#xiaomusic_music_list_json").val(res.content);
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

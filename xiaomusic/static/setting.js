$(function(){
  // 拉取版本
  $.get("/getversion", function(data, status) {
    console.log(data, status, data["version"]);
    $("#version").text(`(${data.version})`);
  });

  // 拉取现有配置
  $.get("/getsetting", function(data, status) {
    console.log(data, status);

    var mi_did_div = $("#mi_did")
    mi_did_div.empty();
    $.each(data.mi_did_list, function(index, option){
      mi_did_div.append($('<option>', {
        value:option,
        text:option,
      }));
      if (data.mi_did == option) {
        mi_did_div.val(option);
      }
    });

    var mi_hardware_div = $("#mi_hardware")
    mi_hardware_div.empty();
    $.each(data.mi_hardware_list, function(index, option){
      mi_hardware_div.append($('<option>', {
        value:option,
        text:option,
      }));
      if (data.mi_hardware == option) {
        mi_hardware_div.val(option);
      }
    });

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

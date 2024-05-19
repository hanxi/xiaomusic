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
  });

  $("#save").on("click", () => {
    var mi_did = $("#mi_did").val();
    var mi_hardware = $("#mi_hardware").val();
    var xiaomusic_search = $("#xiaomusic_search").val();
    var xiaomusic_proxy = $("#xiaomusic_proxy").val();
    console.log("mi_did", mi_did);
    console.log("mi_hardware", mi_hardware);
    console.log("xiaomusic_search", xiaomusic_search);
    console.log("xiaomusic_proxy", xiaomusic_proxy);
    var data = {
      mi_did: mi_did,
      mi_hardware: mi_hardware,
      xiaomusic_search: xiaomusic_search,
      xiaomusic_proxy: xiaomusic_proxy,
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
});

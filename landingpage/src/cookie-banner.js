const STORAGE_KEY = "cookie_banner_dismissed";

if (localStorage.getItem(STORAGE_KEY) !== "1") {
  var banner = document.getElementById("cookie-banner");
  if (banner) {
    banner.style.display = "flex";
    document
      .getElementById("cookie-banner-dismiss")
      .addEventListener("click", function () {
        localStorage.setItem(STORAGE_KEY, "1");
        banner.style.display = "none";
      });
  }
}

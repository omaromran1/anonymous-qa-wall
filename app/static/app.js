"use strict";
// HTMX normally leaves 4xx responses unswapped. Show safe server errors in a
// dedicated live region without replacing or losing the user's form contents.
document.addEventListener("htmx:beforeSwap", function (event) {
  if (event.detail.xhr.status >= 400 && event.detail.xhr.status < 500) {
    event.detail.target = document.getElementById("notice");
    event.detail.shouldSwap = true;
    event.detail.isError = false;
    event.detail.swapOverride = "innerHTML";
  }
});
document.addEventListener("htmx:sendError", function () {
  document.getElementById("notice").textContent =
    "Connection interrupted. Your action may have completed. Reload before retrying a vote.";
});

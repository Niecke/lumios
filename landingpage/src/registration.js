// registration.js — dynamic registration / waitlist section
//
// Fetches /api/v1/public/registration_status from the backend.
// If spots are available: shows "Create account" button (links to frontend /register).
// If full: shows the waitlist email form (POSTs to /api/v1/public/waitlist).
//
// %%BACKEND_URL%% is replaced at Docker build time via sed (same as %%APP_URL%%).

(function () {
  var BACKEND_URL = "%%BACKEND_URL%%";

  var elRegister  = document.getElementById("access-register");
  var elWaitlist  = document.getElementById("access-waitlist");
  var elFallback  = document.getElementById("access-fallback");
  var elHeroCta   = document.getElementById("hero-cta");

  function showRegister() {
    elFallback.classList.add("hidden");
    elRegister.classList.remove("hidden");
    elWaitlist.classList.add("hidden");
    if (elHeroCta) {
      elHeroCta.textContent = "Create account";
      elHeroCta.href = "%%APP_URL%%/register";
    }
  }

  function showWaitlist() {
    elFallback.classList.add("hidden");
    elRegister.classList.add("hidden");
    elWaitlist.classList.remove("hidden");
    if (elHeroCta) {
      elHeroCta.textContent = "Join waitlist";
      elHeroCta.href = "#access";
    }
  }

  fetch(BACKEND_URL + "/api/v1/public/registration_status", { credentials: "omit" })
    .then(function (r) { return r.json(); })
    .then(function (data) {
      if (data.can_register) {
        showRegister();
      } else {
        showWaitlist();
      }
    })
    .catch(function () {
      // Keep fallback visible on network error — nothing to do.
    });

  // Waitlist form submission
  var form     = document.getElementById("waitlist-form");
  var emailEl  = document.getElementById("waitlist-email");
  var btnEl    = document.getElementById("waitlist-btn");
  var msgEl    = document.getElementById("waitlist-msg");

  if (form) {
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var email = emailEl.value.trim();
      if (!email) return;

      btnEl.disabled = true;
      btnEl.textContent = "Joining…";

      fetch(BACKEND_URL + "/api/v1/public/waitlist", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "omit",
        body: JSON.stringify({ email: email }),
      })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          if (data.ok) {
            form.classList.add("hidden");
            msgEl.classList.remove("hidden");
            msgEl.textContent = "You're on the list! We'll email you when a spot opens up.";
            msgEl.style.color = "#166534";
          } else {
            btnEl.disabled = false;
            btnEl.textContent = "Join waitlist";
            msgEl.classList.remove("hidden");
            msgEl.textContent = data.error || "Something went wrong. Please try again.";
            msgEl.style.color = "#991b1b";
          }
        })
        .catch(function () {
          btnEl.disabled = false;
          btnEl.textContent = "Join waitlist";
          msgEl.classList.remove("hidden");
          msgEl.textContent = "Could not reach the server. Please try again later.";
          msgEl.style.color = "#991b1b";
        });
    });
  }
})();

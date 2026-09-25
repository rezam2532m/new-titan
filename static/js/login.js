/* ============================================================
   TiTaN Login — password-only (default: TiTaN)
============================================================ */

(function () {

    const form =
        document.getElementById("loginForm");

    const password =
        document.getElementById("password");

    const passwordRow =
        document.getElementById("passwordRow");

    const message =
        document.getElementById("message");

    const loginButton =
        document.getElementById("loginButton");

    // Force visible — password-only login, never hide the field.
    // Fixes cached CSS/JS where .password-row was display:none until /api/me
    if (passwordRow) {
        passwordRow.classList.add("visible");
        passwordRow.style.display = "flex";
        passwordRow.style.visibility = "visible";
        passwordRow.style.opacity = "1";
    }
    if (password) {
        // Ensure focused and visible even if browser restores hidden state
        try { password.focus(); } catch (e) {}
    }


    /* ============================================================
       LOGIN — password-only, username is fixed to TiTaN (hidden)
    ============================================================ */

    form.addEventListener("submit", async function (event) {

        event.preventDefault();

        const pass =
            (password && password.value) || "";


        if (!pass) {

            showMessage(
                "لطفاً رمز عبور را وارد کنید.",
                "error"
            );

            if (password) password.focus();

            return;

        }


        loginButton.disabled = true;

        loginButton.classList.add("loading");

        loginButton.querySelector("span").textContent =
            "در حال ورود...";


        showMessage(
            "در حال بررسی اطلاعات...",
            "normal"
        );


        try {

            const response = await fetch("/api/login", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    username: "TiTaN",
                    password: pass,
                    remember: true
                })
            });

            let data = {};
            try { data = await response.json(); } catch (e) { /* noop */ }

            if (response.ok && data.ok) {

                showMessage(
                    "ورود موفق — در حال انتقال...",
                    "success"
                );

                setTimeout(function () {
                    window.location.href = "/dashboard";
                }, 350);

                return;
            }

            const detail = data.detail || "";

            if (response.status === 429 && detail.indexOf("locked") === 0) {
                const secs = parseInt(detail.split(":")[1] || "60", 10);
                showMessage(
                    "تلاش‌های زیاد — " + secs + " ثانیه بعد دوباره امتحان کنید.",
                    "error"
                );
            } else if (response.status === 401) {
                showMessage(
                    "رمز عبور اشتباه است.",
                    "error"
                );
            } else {
                showMessage(
                    "خطایی هنگام ورود رخ داد.",
                    "error"
                );
            }

        } catch (error) {

            console.error(error);

            showMessage(
                "عدم اتصال به سرور — اتصال اینترنت را بررسی کنید.",
                "error"
            );

        }


        loginButton.disabled = false;

        loginButton.classList.remove("loading");

        loginButton.querySelector("span").textContent =
            "ورود";

    });


    /* ============================================================
       MESSAGE
    ============================================================ */

    function showMessage(text, type) {

        message.textContent =
            text;

        message.className =
            "message";

        if (type) {
            message.classList.add(type);
        }

    }


    /* ============================================================
       INPUT — clear message on typing
    ============================================================ */

    if (password) {
        password.addEventListener(
            "input",
            function () {
                message.textContent = "";
                message.className = "message";
            }
        );
        password.addEventListener(
            "keydown",
            function (event) {
                if (event.key === "Enter") {
                    event.preventDefault();
                    form.requestSubmit();
                }
            }
        );
    }

})();

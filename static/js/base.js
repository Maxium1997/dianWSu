const header = document.querySelector("[data-site-header]");
const nav = document.querySelector("[data-site-nav]");
const navToggle = document.querySelector("[data-nav-toggle]");
const themeToggle = document.querySelector("[data-theme-toggle]");
const themeLabel = document.querySelector("[data-theme-label]");
const themeIcon = document.querySelector("[data-theme-icon]");

function currentTheme() {
    return document.documentElement.dataset.theme === "dark" ? "dark" : "light";
}

function applyTheme(theme, persist = false) {
    document.documentElement.dataset.theme = theme;
    document.documentElement.style.colorScheme = theme;

    if (persist) {
        try {
            localStorage.setItem("dianwsu-theme", theme);
        } catch (error) {
            // Theme still works for this page when storage is unavailable.
        }
    }

    if (themeToggle) {
        const isDark = theme === "dark";
        themeToggle.setAttribute("aria-pressed", String(isDark));
        themeToggle.setAttribute("aria-label", isDark ? "切換為淺色模式" : "切換為深色模式");
        if (themeLabel) themeLabel.textContent = isDark ? "淺色模式" : "深色模式";
        if (themeIcon) themeIcon.textContent = isDark ? "○" : "●";
    }
}

function syncHeaderState() {
    if (!header) return;
    header.classList.toggle("is-scrolled", window.scrollY > 8);
}

function closeNav() {
    if (!nav || !navToggle) return;
    nav.classList.remove("is-open");
    navToggle.setAttribute("aria-expanded", "false");
    document.body.classList.remove("nav-open");
}

if (navToggle && nav) {
    navToggle.addEventListener("click", () => {
        const isOpen = nav.classList.toggle("is-open");
        navToggle.setAttribute("aria-expanded", String(isOpen));
        document.body.classList.toggle("nav-open", isOpen);
    });

    nav.addEventListener("click", (event) => {
        if (event.target instanceof HTMLAnchorElement) {
            closeNav();
        }
    });
}

if (themeToggle) {
    applyTheme(currentTheme());
    themeToggle.addEventListener("click", () => {
        applyTheme(currentTheme() === "dark" ? "light" : "dark", true);
    });
}

window.addEventListener("scroll", syncHeaderState, { passive: true });
window.addEventListener("resize", () => {
    if (window.innerWidth > 680) {
        closeNav();
    }
});

syncHeaderState();

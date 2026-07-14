const header = document.querySelector("[data-site-header]");
const nav = document.querySelector("[data-site-nav]");
const navToggle = document.querySelector("[data-nav-toggle]");

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

window.addEventListener("scroll", syncHeaderState, { passive: true });
window.addEventListener("resize", () => {
    if (window.innerWidth > 680) {
        closeNav();
    }
});

syncHeaderState();

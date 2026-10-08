// main.js — app JavaScript

// Mobile navigation toggle
(function () {
    function initNavToggle() {
        var toggle = document.getElementById('navToggle');
        var links = document.getElementById('navLinks');
        if (!toggle || !links) return;

        function closeMenu() {
            links.classList.remove('open');
            toggle.classList.remove('open');
            toggle.setAttribute('aria-expanded', 'false');
        }

        function openMenu() {
            links.classList.add('open');
            toggle.classList.add('open');
            toggle.setAttribute('aria-expanded', 'true');
        }

        toggle.addEventListener('click', function (e) {
            e.stopPropagation();
            if (links.classList.contains('open')) {
                closeMenu();
            } else {
                openMenu();
            }
        });

        // Close when a link is tapped
        links.addEventListener('click', function (e) {
            if (e.target.tagName === 'A') closeMenu();
        });

        // Close when clicking outside the nav
        document.addEventListener('click', function (e) {
            if (!links.classList.contains('open')) return;
            if (!links.contains(e.target) && !toggle.contains(e.target)) closeMenu();
        });

        // Reset when resizing up to desktop
        window.addEventListener('resize', function () {
            if (window.innerWidth > 600) closeMenu();
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initNavToggle);
    } else {
        initNavToggle();
    }
})();

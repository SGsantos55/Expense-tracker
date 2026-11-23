(function () {
    var modal = document.getElementById('exportModal');
    var openBtn = document.getElementById('exportOpen');
    if (!modal || !openBtn) return;

    var format = 'excel';
    var template = 'minimal';
    var templates = document.getElementById('exportTemplates');

    function open() {
        modal.classList.add('active');
        modal.setAttribute('aria-hidden', 'false');
    }
    function close() {
        modal.classList.remove('active');
        modal.setAttribute('aria-hidden', 'true');
    }
    function select(nodes, active) {
        nodes.forEach(function (n) { n.classList.toggle('active', n === active); });
    }

    openBtn.addEventListener('click', open);
    document.getElementById('exportClose').addEventListener('click', close);
    document.getElementById('exportCancel').addEventListener('click', close);
    modal.addEventListener('click', function (e) { if (e.target === modal) close(); });
    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && modal.classList.contains('active')) close();
    });

    var formatBtns = Array.prototype.slice.call(modal.querySelectorAll('.export-format'));
    formatBtns.forEach(function (btn) {
        btn.addEventListener('click', function () {
            format = btn.dataset.format;
            select(formatBtns, btn);
            templates.classList.toggle('hidden', format !== 'excel');
        });
    });

    var cards = Array.prototype.slice.call(modal.querySelectorAll('.export-card'));
    cards.forEach(function (card) {
        card.addEventListener('click', function () {
            template = card.dataset.template;
            select(cards, card);
        });
    });

    document.getElementById('exportGo').addEventListener('click', function () {
        var params = new URLSearchParams();
        if (modal.dataset.dateFrom) params.set('date_from', modal.dataset.dateFrom);
        if (modal.dataset.dateTo) params.set('date_to', modal.dataset.dateTo);
        var base = modal.dataset.pdfUrl;
        if (format === 'excel') {
            params.set('template', template);
            base = modal.dataset.excelUrl;
        }
        var qs = params.toString();
        window.location.href = qs ? base + '?' + qs : base;
        close();
    });
})();

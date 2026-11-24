(function () {
    var modal = document.getElementById('exportModal');
    var openBtn = document.getElementById('exportOpen');
    if (!modal || !openBtn) return;

    var template = 'minimal';

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
        params.set('template', template);
        var qs = params.toString();
        window.location.href = modal.dataset.excelUrl + '?' + qs;
        close();
    });
})();

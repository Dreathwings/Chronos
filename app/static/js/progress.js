(function() {
  function parseNumber(value, fallback) {
    const numeric = Number.parseFloat(value);
    if (Number.isFinite(numeric) && numeric >= 0) {
      return numeric;
    }
    return fallback;
  }

  function formatDuration(seconds) {
    if (!Number.isFinite(seconds) || seconds <= 0) {
      return 'Moins de 5 s';
    }
    const totalSeconds = Math.round(seconds);
    const minutes = Math.floor(totalSeconds / 60);
    const remainder = totalSeconds % 60;
    if (minutes <= 0) {
      return `${totalSeconds} s`;
    }
    if (minutes === 1) {
      return remainder > 0 ? `1 min ${remainder} s` : '1 min';
    }
    return remainder > 0 ? `${minutes} min ${remainder} s` : `${minutes} min`;
  }

  function clamp(value, min, max) {
    return Math.min(Math.max(value, min), max);
  }

  document.addEventListener('DOMContentLoaded', function() {
    const modalEl = document.getElementById('generationProgressModal');
    if (!modalEl) {
      return;
    }
    const progressBar = modalEl.querySelector('[data-chronos-progress-bar]');
    const percentLabel = modalEl.querySelector('[data-chronos-progress-percent]');
    const etaLabel = modalEl.querySelector('[data-chronos-progress-eta]');
    const detailLabel = modalEl.querySelector('[data-chronos-progress-detail]');
    const stateLabel = modalEl.querySelector('[data-chronos-progress-state]');
    if (!progressBar || !percentLabel || !etaLabel || !detailLabel || !stateLabel) {
      return;
    }

    const bootstrapLib = window.bootstrap || null;
    if (!bootstrapLib || typeof bootstrapLib.Modal !== 'function') {
      return;
    }

    const modal = new bootstrapLib.Modal(modalEl, {
      backdrop: 'static',
      keyboard: false,
    });

    let intervalId = null;
    let startTimestamp = 0;
    let estimatedSeconds = 0;
    let running = false;

    function stopTimer() {
      if (intervalId !== null) {
        window.clearInterval(intervalId);
        intervalId = null;
      }
      running = false;
    }

    function updateProgress() {
      if (!running) {
        return;
      }
      const elapsedSeconds = (performance.now() - startTimestamp) / 1000;
      let ratio = estimatedSeconds > 0 ? elapsedSeconds / estimatedSeconds : 0;
      let displayPercent;
      if (ratio < 1) {
        displayPercent = clamp(Math.round(ratio * 100), 1, 95);
        stateLabel.textContent = 'Génération en cours…';
        const remaining = Math.max(estimatedSeconds - elapsedSeconds, 0);
        etaLabel.textContent = formatDuration(remaining);
      } else {
        const overtime = Math.min((elapsedSeconds - estimatedSeconds) / (estimatedSeconds || 1), 1.5);
        const extra = Math.round(clamp(overtime * 5, 1, 5));
        displayPercent = clamp(95 + extra, 96, 99);
        stateLabel.textContent = 'Finalisation…';
        etaLabel.textContent = 'Calcul en cours';
      }
      progressBar.style.width = `${displayPercent}%`;
      progressBar.setAttribute('aria-valuenow', String(displayPercent));
      percentLabel.textContent = `${displayPercent}%`;
    }

    function beginProgress(form) {
      if (running) {
        return;
      }
      const hours = parseNumber(form.getAttribute('data-chronos-progress-hours'), 0);
      const tasks = parseNumber(form.getAttribute('data-chronos-progress-tasks'), 0);
      const baseline = parseNumber(form.getAttribute('data-chronos-progress-baseline'), 6);
      const perUnit = parseNumber(form.getAttribute('data-chronos-progress-per-unit'), 3.5);
      const label = form.getAttribute('data-chronos-progress-label');
      const context = form.getAttribute('data-chronos-progress-context') || '';

      let magnitude = hours;
      if (!magnitude || magnitude <= 0) {
        magnitude = tasks > 0 ? tasks : 1;
      }
      estimatedSeconds = clamp(baseline + magnitude * perUnit, 6, 600);

      startTimestamp = performance.now();
      progressBar.style.width = '1%';
      progressBar.setAttribute('aria-valuenow', '1');
      percentLabel.textContent = '1%';
      stateLabel.textContent = 'Initialisation…';
      etaLabel.textContent = formatDuration(estimatedSeconds);

      if (label && label.trim().length > 0) {
        detailLabel.textContent = label;
        detailLabel.classList.remove('d-none');
      } else if (context === 'bulk' && Number.isFinite(hours) && hours > 0) {
        detailLabel.textContent = `Prévision basée sur ${Math.round(hours)} heure(s) restante(s).`;
        detailLabel.classList.remove('d-none');
      } else {
        detailLabel.textContent = '';
        detailLabel.classList.add('d-none');
      }

      running = true;
      modal.show();
      updateProgress();
      intervalId = window.setInterval(updateProgress, 250);
    }

    document.querySelectorAll('form[data-chronos-progress]').forEach(function(form) {
      form.addEventListener('submit', function() {
        beginProgress(form);
      }, { once: false });
    });

    window.addEventListener('pageshow', function() {
      stopTimer();
      if (modalEl.classList.contains('show')) {
        modal.hide();
      }
    });

    window.addEventListener('beforeunload', function() {
      stopTimer();
    });
  });
})();

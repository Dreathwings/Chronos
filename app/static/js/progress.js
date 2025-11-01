(function() {
  function parseNumber(value, fallback) {
    const numeric = Number.parseFloat(value);
    if (Number.isFinite(numeric) && numeric >= 0) {
      return numeric;
    }
    return fallback;
  }

  function clamp(value, min, max) {
    return Math.min(Math.max(value, min), max);
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

  function computeEstimate(form) {
    const hours = parseNumber(form.getAttribute('data-chronos-progress-hours'), 0);
    const tasks = parseNumber(form.getAttribute('data-chronos-progress-tasks'), 0);
    const baseline = parseNumber(form.getAttribute('data-chronos-progress-baseline'), 6);
    const perUnit = parseNumber(form.getAttribute('data-chronos-progress-per-unit'), 3.5);
    const labelText = form.getAttribute('data-chronos-progress-label') || '';
    const context = form.getAttribute('data-chronos-progress-context') || '';

    let magnitude = hours;
    if (!magnitude || magnitude <= 0) {
      magnitude = tasks > 0 ? tasks : 1;
    }
    const estimatedSeconds = clamp(baseline + magnitude * perUnit, 6, 900);

    let detailText = '';
    if (labelText.trim().length > 0) {
      detailText = labelText;
    } else if (context === 'bulk' && Number.isFinite(hours) && hours > 0) {
      detailText = `Prévision basée sur ${Math.round(hours)} heure(s) restante(s).`;
    }

    return {
      estimatedSeconds,
      detailText,
      labelText,
    };
  }

  function createOverlay(modalEl) {
    const progressBar = modalEl.querySelector('[data-chronos-progress-bar]');
    const percentLabel = modalEl.querySelector('[data-chronos-progress-percent]');
    const etaLabel = modalEl.querySelector('[data-chronos-progress-eta]');
    const detailLabel = modalEl.querySelector('[data-chronos-progress-detail]');
    const stateLabel = modalEl.querySelector('[data-chronos-progress-state]');
    const weekPanel = modalEl.querySelector('[data-chronos-week-panel]');
    const weekLabel = modalEl.querySelector('[data-chronos-week-label]');
    const weekBody = modalEl.querySelector('[data-chronos-week-body]');
    if (!progressBar || !percentLabel || !etaLabel || !detailLabel || !stateLabel) {
      return null;
    }

    const bootstrapLib = window.bootstrap || null;
    if (!bootstrapLib || typeof bootstrapLib.Modal !== 'function') {
      return null;
    }

    const modal = new bootstrapLib.Modal(modalEl, {
      backdrop: 'static',
      keyboard: false,
    });

    let intervalId = null;
    let startTimestamp = 0;
    let estimatedSeconds = 0;
    let mode = 'idle';
    let detailFallback = '';

    function stopTimer() {
      if (intervalId !== null) {
        window.clearInterval(intervalId);
        intervalId = null;
      }
    }

    function applyDetail(text) {
      if (text && text.trim().length > 0) {
        detailLabel.textContent = text;
        detailLabel.classList.remove('d-none');
      } else {
        detailLabel.textContent = '';
        detailLabel.classList.add('d-none');
      }
    }

    function clearWeekTable() {
      if (!weekPanel || !weekLabel || !weekBody) {
        return;
      }
      weekLabel.textContent = '';
      weekBody.innerHTML = '';
      weekPanel.classList.add('d-none');
    }

    function renderWeekTable(snapshot) {
      if (!weekPanel || !weekLabel || !weekBody) {
        return;
      }
      const label = snapshot && typeof snapshot.current_week_label === 'string'
        ? snapshot.current_week_label.trim()
        : '';
      const entries = snapshot && Array.isArray(snapshot.current_week_sessions)
        ? snapshot.current_week_sessions
        : [];
      if (!label || entries.length === 0) {
        clearWeekTable();
        return;
      }
      weekLabel.textContent = label;
      weekBody.innerHTML = '';
      entries.forEach(function(entry) {
        const row = document.createElement('tr');
        const fields = [
          entry.course,
          entry.class_label,
          entry.subgroup,
          entry.teacher,
          entry.time,
          entry.type,
        ];
        fields.forEach(function(value, index) {
          const cell = document.createElement('td');
          const content = typeof value === 'string' && value.trim().length > 0 ? value : '—';
          cell.textContent = content;
          if (index === 2 && content === '—') {
            cell.classList.add('text-muted');
          }
          row.appendChild(cell);
        });
        weekBody.appendChild(row);
      });
      weekPanel.classList.remove('d-none');
    }

    function updateTimer() {
      const elapsedSeconds = (performance.now() - startTimestamp) / 1000;
      let percent;
      if (estimatedSeconds <= 0) {
        percent = 50;
        etaLabel.textContent = 'Calcul en cours';
      } else {
        const ratio = elapsedSeconds / estimatedSeconds;
        if (ratio < 1) {
          percent = clamp(Math.round(ratio * 100), 1, 95);
          const remaining = Math.max(estimatedSeconds - elapsedSeconds, 0);
          etaLabel.textContent = formatDuration(remaining);
          stateLabel.textContent = 'Génération en cours…';
        } else {
          const overtime = Math.min((elapsedSeconds - estimatedSeconds) / (estimatedSeconds || 1), 1.5);
          const extra = Math.round(clamp(overtime * 5, 1, 5));
          percent = clamp(95 + extra, 96, 99);
          etaLabel.textContent = 'Calcul en cours';
          stateLabel.textContent = 'Finalisation…';
        }
      }
      progressBar.style.width = `${percent}%`;
      progressBar.setAttribute('aria-valuenow', String(percent));
      percentLabel.textContent = `${percent}%`;
    }

    function setPercent(value) {
      const display = clamp(Math.round(value), 0, 100);
      progressBar.style.width = `${display}%`;
      progressBar.setAttribute('aria-valuenow', String(display));
      percentLabel.textContent = `${display}%`;
    }

    return {
      show(options) {
        stopTimer();
        const initialMode = options && options.mode ? options.mode : 'async';
        mode = initialMode;
        detailFallback = (options && options.detailText) || '';
        estimatedSeconds = options && options.estimatedSeconds ? options.estimatedSeconds : 0;
        clearWeekTable();

        setPercent(1);
        stateLabel.textContent = 'Initialisation…';
        if (estimatedSeconds > 0) {
          etaLabel.textContent = formatDuration(estimatedSeconds);
        } else {
          etaLabel.textContent = 'Calcul en cours';
        }
        applyDetail(detailFallback);

        modal.show();

        if (mode === 'estimate') {
          startTimestamp = performance.now();
          updateTimer();
          intervalId = window.setInterval(updateTimer, 250);
        }
      },
      setLabel(text) {
        detailFallback = text || detailFallback;
        applyDetail(detailFallback);
      },
      update(snapshot) {
        if (!snapshot) {
          return;
        }
        stopTimer();
        mode = 'async';

        const percent = Number.isFinite(snapshot.percent)
          ? snapshot.percent
          : Number.parseFloat(snapshot.percent);
        if (Number.isFinite(percent)) {
          setPercent(percent);
        }

        if (snapshot.state === 'running') {
          stateLabel.textContent = 'Génération en cours…';
        } else if (snapshot.state === 'success') {
          stateLabel.textContent = snapshot.message || 'Génération terminée';
        } else if (snapshot.state === 'error') {
          stateLabel.textContent = 'Erreur lors de la génération';
        } else {
          stateLabel.textContent = 'Initialisation…';
        }

        if (Number.isFinite(snapshot.eta_seconds) && snapshot.state === 'running') {
          etaLabel.textContent = formatDuration(snapshot.eta_seconds);
        } else if (snapshot.state === 'success') {
          etaLabel.textContent = 'Terminé';
        } else if (snapshot.state === 'error') {
          etaLabel.textContent = 'Erreur';
        } else {
          etaLabel.textContent = 'Calcul en cours';
        }

        const detail = snapshot.detail && snapshot.detail.trim().length > 0
          ? snapshot.detail
          : detailFallback;
        applyDetail(detail);
        renderWeekTable(snapshot);
      },
      finish(message) {
        stopTimer();
        mode = 'idle';
        setPercent(100);
        stateLabel.textContent = message || 'Génération terminée';
        etaLabel.textContent = 'Terminé';
        if (message && message.trim().length > 0) {
          applyDetail(message);
        }
      },
      fail(message) {
        stopTimer();
        mode = 'idle';
        stateLabel.textContent = 'Erreur lors de la génération';
        etaLabel.textContent = 'Erreur';
        applyDetail(message || 'Une erreur est survenue pendant la génération.');
        window.setTimeout(function() {
          modal.hide();
          if (message && message.trim().length > 0) {
            window.alert(message);
          }
        }, 400);
      },
      hide() {
        stopTimer();
        mode = 'idle';
        modal.hide();
      },
      stop() {
        stopTimer();
      },
    };
  }

  document.addEventListener('DOMContentLoaded', function() {
    const modalEl = document.getElementById('generationProgressModal');
    if (!modalEl) {
      return;
    }

    const overlay = createOverlay(modalEl);
    if (!overlay) {
      return;
    }

    let activeJob = null;

    function clearActiveJob() {
      if (activeJob && activeJob.timeoutId) {
        window.clearTimeout(activeJob.timeoutId);
      }
      activeJob = null;
    }

    function scheduleNextPoll(job) {
      job.timeoutId = window.setTimeout(function() {
        pollJob(job);
      }, 500);
    }

    function pollJob(job) {
      activeJob = job;
      fetch(job.statusUrl, {
        headers: {
          Accept: 'application/json',
          'Cache-Control': 'no-store',
        },
        credentials: 'same-origin',
      })
        .then(function(response) {
          if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
          }
          return response.json();
        })
        .then(function(snapshot) {
          overlay.update(snapshot);
          if (!snapshot.finished) {
            scheduleNextPoll(job);
            return;
          }
          clearActiveJob();
          if (snapshot.state === 'success') {
            overlay.finish(snapshot.message);
            window.setTimeout(function() {
              window.location.assign(job.redirectUrl || window.location.href);
            }, 600);
          } else {
            if (job.submitter) {
              job.submitter.disabled = false;
            }
            overlay.fail(snapshot.message || 'Erreur lors de la génération.');
          }
        })
        .catch(function(error) {
          clearActiveJob();
          if (job.submitter) {
            job.submitter.disabled = false;
          }
          overlay.fail(`Suivi interrompu : ${error.message}`);
        });
    }

    function startAsync(form, submitter) {
      const estimate = computeEstimate(form);
      if (submitter) {
        submitter.disabled = true;
      }
      overlay.show({
        mode: 'async',
        detailText: estimate.detailText || estimate.labelText,
        estimatedSeconds: estimate.estimatedSeconds,
      });

      const action = form.getAttribute('action') || window.location.href;
      const method = (form.getAttribute('method') || 'POST').toUpperCase();
      const formData = new FormData(form);

      fetch(action, {
        method: method === 'GET' ? 'POST' : method,
        body: formData,
        headers: {
          'X-Requested-With': 'XMLHttpRequest',
          Accept: 'application/json',
        },
        credentials: 'same-origin',
      })
        .then(function(response) {
          if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
          }
          return response.json();
        })
        .then(function(payload) {
          if (!payload || !payload.job_id || !payload.status_url) {
            throw new Error('Réponse inattendue du serveur');
          }
          if (payload.label) {
            overlay.setLabel(payload.label);
          }
          const job = {
            id: payload.job_id,
            statusUrl: payload.status_url,
            redirectUrl: payload.redirect_url || window.location.href,
            submitter: submitter || null,
          };
          pollJob(job);
        })
        .catch(function(error) {
          if (submitter) {
            submitter.disabled = false;
          }
          overlay.fail(`Impossible de lancer la génération : ${error.message}`);
        });
    }

    document.querySelectorAll('form[data-chronos-progress]').forEach(function(form) {
      const asyncMode = form.getAttribute('data-chronos-progress-async') === 'true';
      if (asyncMode) {
        form.addEventListener('submit', function(event) {
          event.preventDefault();
          const submitter = event.submitter || form.querySelector('[type="submit"]');
          startAsync(form, submitter);
        });
      } else {
        form.addEventListener('submit', function() {
          const estimate = computeEstimate(form);
          overlay.show({
            mode: 'estimate',
            detailText: estimate.detailText || estimate.labelText,
            estimatedSeconds: estimate.estimatedSeconds,
          });
        });
      }
    });

    window.addEventListener('pageshow', function() {
      overlay.hide();
      clearActiveJob();
    });

    window.addEventListener('beforeunload', function() {
      overlay.stop();
      clearActiveJob();
    });
  });
})();


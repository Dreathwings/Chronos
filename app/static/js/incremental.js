(function() {
  function parseInteger(value) {
    const parsed = Number.parseInt(value, 10);
    return Number.isFinite(parsed) ? parsed : null;
  }

  function parseFloatValue(value) {
    const parsed = Number.parseFloat(value);
    return Number.isFinite(parsed) ? parsed : null;
  }

  function parseIdList(value) {
    if (!value) {
      return [];
    }
    return Array.from(
      new Set(
        value
          .split(/[\s,;]+/)
          .map(function(entry) {
            return Number.parseInt(entry, 10);
          })
          .filter(function(id) {
            return Number.isFinite(id);
          })
      )
    );
  }

  function formatDateTime(value) {
    if (!value) {
      return '—';
    }
    const date = new Date(value);
    if (!Number.isFinite(date.getTime())) {
      return value;
    }
    try {
      return new Intl.DateTimeFormat('fr-FR', {
        dateStyle: 'short',
        timeStyle: 'short',
      }).format(date);
    } catch (err) {
      return date.toLocaleString();
    }
  }

  function formatNumber(value) {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) {
      return '0';
    }
    try {
      return new Intl.NumberFormat('fr-FR').format(numeric);
    } catch (err) {
      return String(numeric);
    }
  }

  function setStatus(alertEl, message, level) {
    if (!alertEl) {
      return;
    }
    alertEl.textContent = message;
    alertEl.classList.remove('d-none', 'alert-success', 'alert-danger', 'alert-warning');
    if (level === 'success') {
      alertEl.classList.add('alert-success');
    } else if (level === 'warning') {
      alertEl.classList.add('alert-warning');
    } else {
      alertEl.classList.add('alert-danger');
    }
  }

  function hideStatus(alertEl) {
    if (!alertEl) {
      return;
    }
    alertEl.textContent = '';
    alertEl.classList.add('d-none');
    alertEl.classList.remove('alert-success', 'alert-danger', 'alert-warning');
  }

  function toggleElement(element, visible) {
    if (!element) {
      return;
    }
    if (visible) {
      element.classList.remove('d-none');
    } else {
      element.classList.add('d-none');
    }
  }

  document.addEventListener('DOMContentLoaded', function() {
    const form = document.querySelector('[data-incremental-form]');
    if (!form) {
      return;
    }

    const submitButton = form.querySelector('[data-incremental-submit]');
    const defaultButtonLabel = submitButton ? submitButton.textContent.trim() : '';
    const outputContainer = document.querySelector('[data-incremental-output]');
    const statusAlert = document.querySelector('[data-incremental-status]');
    const summaryContainer = document.querySelector('[data-incremental-summary]');
    const tableWrapper = document.querySelector('[data-incremental-table]');
    const tableBody = document.querySelector('[data-incremental-rows]');
    const emptyLabel = document.querySelector('[data-incremental-empty]');

    function setLoading(loading) {
      if (!submitButton) {
        return;
      }
      submitButton.disabled = loading;
      submitButton.textContent = loading ? 'Calcul en cours…' : defaultButtonLabel;
    }

    function resetResult() {
      hideStatus(statusAlert);
      toggleElement(outputContainer, false);
      if (summaryContainer) {
        summaryContainer.innerHTML = '';
        summaryContainer.classList.add('d-none');
      }
      if (tableBody) {
        tableBody.innerHTML = '';
      }
      toggleElement(tableWrapper, false);
      toggleElement(emptyLabel, false);
    }

    function renderSummary(data) {
      if (!summaryContainer) {
        return;
      }
      const summary = data.summary || {};
      const sessions = Array.isArray(data.sessions) ? data.sessions.length : 0;
      summaryContainer.innerHTML = '';

      const heading = document.createElement('h3');
      heading.className = 'h6 text-uppercase text-muted mb-2';
      heading.textContent = 'Résumé';
      summaryContainer.appendChild(heading);

      const list = document.createElement('ul');
      list.className = 'list-unstyled mb-0';
      const items = [
        `État du solveur : ${data.status || '—'}`,
        data.version ? `Nouvelle version : ${data.version}` : null,
        `Séances verrouillées conservées : ${formatNumber(summary.locked || 0)}`,
        `Séances replanifiées : ${formatNumber(summary.replanned || 0)}`,
        `Soft-lock déplacés : ${formatNumber(summary.soft_moved || 0)}`,
        `Séances dans la réponse : ${formatNumber(sessions)}`,
      ].filter(Boolean);

      items.forEach(function(text) {
        const item = document.createElement('li');
        item.textContent = text;
        list.appendChild(item);
      });

      summaryContainer.appendChild(list);
      summaryContainer.classList.remove('d-none');
    }

    function renderSessions(sessions) {
      if (!tableBody || !emptyLabel || !tableWrapper) {
        return;
      }
      tableBody.innerHTML = '';
      if (!sessions || sessions.length === 0) {
        toggleElement(tableWrapper, false);
        toggleElement(emptyLabel, true);
        return;
      }

      sessions.forEach(function(session) {
        const row = document.createElement('tr');
        const fields = [
          session.id,
          formatDateTime(session.start),
          formatDateTime(session.end),
          session.room_id != null ? session.room_id : '—',
          session.teacher_id != null ? session.teacher_id : '—',
          session.group_id != null ? session.group_id : '—',
        ];
        fields.forEach(function(value, index) {
          const cell = document.createElement('td');
          cell.textContent = value === null || value === undefined ? '—' : String(value);
          if (index >= 3 && value === '—') {
            cell.classList.add('text-muted');
          }
          row.appendChild(cell);
        });
        tableBody.appendChild(row);
      });

      toggleElement(emptyLabel, false);
      toggleElement(tableWrapper, true);
    }

    form.addEventListener('submit', function(event) {
      event.preventDefault();
      resetResult();

      const formData = new FormData(form);
      const baseVersion = (formData.get('base_version') || '').toString().trim();
      if (!baseVersion) {
        setStatus(statusAlert, 'Sélectionnez une semaine de référence avant de lancer le solveur.', 'warning');
        toggleElement(outputContainer, true);
        return;
      }

      const freezeRoom = formData.get('freeze_room') !== null;
      const slotMinutes = parseInteger(formData.get('slot_minutes'));
      const softPenalty = parseInteger(formData.get('soft_lock_penalty'));
      const timeLimit = parseFloatValue(formData.get('time_limit_s'));
      const workers = parseInteger(formData.get('workers'));
      const seed = parseInteger(formData.get('seed'));
      const softLocks = parseIdList(formData.get('include_soft_relock_ids'));
      const regenerate = parseIdList(formData.get('regenerate_ids'));

      const payload = {
        freeze_room: freezeRoom,
        slot_minutes: slotMinutes && slotMinutes > 0 ? slotMinutes : 30,
        soft_lock_penalty: softPenalty !== null && softPenalty >= 0 ? softPenalty : 0,
      };

      if (timeLimit !== null && timeLimit >= 0) {
        payload.time_limit_s = timeLimit;
      }
      if (workers !== null && workers >= 0) {
        payload.workers = workers;
      }
      if (seed !== null) {
        payload.seed = seed;
      }
      if (softLocks.length > 0) {
        payload.include_soft_relock_ids = softLocks;
      }
      if (regenerate.length > 0) {
        payload.regenerate_ids = regenerate;
      }

      const action = form.getAttribute('action') || '/api/chronos/generate';
      const query = new URLSearchParams({ mode: 'incremental', base_version: baseVersion });
      const endpoint = `${action}?${query.toString()}`;

      setLoading(true);

      fetch(endpoint, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Requested-With': 'XMLHttpRequest',
          Accept: 'application/json',
        },
        credentials: 'same-origin',
        body: JSON.stringify(payload),
      })
        .then(function(response) {
          return response
            .json()
            .catch(function() {
              return {};
            })
            .then(function(data) {
              return { ok: response.ok, status: response.status, data: data };
            });
        })
        .then(function(result) {
          setLoading(false);
          toggleElement(outputContainer, true);
          if (!result.ok) {
            const errorMessage = result.data && result.data.error
              ? result.data.error
              : `Erreur HTTP ${result.status}`;
            setStatus(statusAlert, errorMessage, result.status >= 500 ? 'danger' : 'warning');
            return;
          }

          setStatus(
            statusAlert,
            `Solveur ${result.data.status || 'OK'} — version ${result.data.version || 'inconnue'}`,
            'success'
          );
          renderSummary(result.data);
          renderSessions(result.data.sessions || []);
        })
        .catch(function(error) {
          setLoading(false);
          toggleElement(outputContainer, true);
          setStatus(statusAlert, `Erreur de communication avec le solveur : ${error.message}`, 'danger');
        });
    });
  });
})();

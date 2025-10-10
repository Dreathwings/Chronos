const ChronosCalendar = {
  mount(elementId) {
    const container = document.getElementById(elementId);
    if (!container) return;

    const events = JSON.parse(container.dataset.events || '[]');

    const calendar = new FullCalendar.Calendar(container, {
      initialView: 'timeGridWeek',
      locale: 'fr',
      headerToolbar: {
        left: 'prev,next today',
        center: 'title',
        right: 'dayGridMonth,timeGridWeek,timeGridDay',
      },
      slotMinTime: '08:00:00',
      slotMaxTime: '19:00:00',
      slotDuration: '01:00:00',
      events,
    });

    calendar.render();
  },
};

window.ChronosCalendar = ChronosCalendar;

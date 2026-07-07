/**
 * CSV → JSON-LD Converter — Frontend Application
 * Handles upload, context selection, mapping editor, conversion, and download.
 */

(function () {
  'use strict';

  // ── State ────────────────────────────────────────────────────────────────
  const state = {
    jobId: null,
    csvHeaders: [],
    csvRowCount: 0,
    selectedContext: null,       // { id, label, properties[], commonTypes[], raw?, isCustom }
    mapping: {},                 // { columnName: { property: "...", datatype: "..." } }
    entityType: '',
    baseIri: '',
    currentStep: 1,
    pollingTimer: null,
  };

  // ── DOM refs ─────────────────────────────────────────────────────────────
  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => document.querySelectorAll(sel);

  const uploadZone = $('#upload-zone');
  const fileInput = $('#csv-file-input');
  const csvPreview = $('#csv-preview');
  const previewTable = $('#preview-table');
  const rowCountDisplay = $('#row-count-display');
  const uploadError = $('#upload-error');
  const btnChangeFile = $('#btn-change-file');

  const contextGrid = $('#context-grid');
  const customContextFile = $('#custom-context-file');
  const customContextName = $('#custom-context-name');
  const contextError = $('#context-error');

  const entityTypeInput = $('#entity-type');
  const entityTypeSuggestions = $('#entity-type-suggestions');
  const baseIriInput = $('#base-iri');
  const mappingArea = $('#mapping-area');
  const mappingEmpty = $('#mapping-empty');
  const mappingList = $('#mapping-list');

  const btnConvert = $('#btn-convert');
  const progressArea = $('#progress-area');
  const progressFill = $('#progress-fill');
  const progressTextEl = $('#progress-text');
  const progressStatus = $('#progress-status');
  const resultArea = $('#result-area');
  const jsonldOutput = $('#jsonld-output');
  const validationInfo = $('#validation-info');
  const convertError = $('#convert-error');
  const btnDownload = $('#btn-download');
  const btnCopy = $('#btn-copy');

  const toast = $('#toast');

  const steps = $$('.step-item');
  const panels = {
    1: $('#panel-step-1'),
    2: $('#panel-step-2'),
    3: $('#panel-step-3'),
    4: $('#panel-step-4'),
  };

  // ── Toast ────────────────────────────────────────────────────────────────
  let toastTimer = null;
  function showToast(message, type = '') {
    if (toastTimer) clearTimeout(toastTimer);
    toast.textContent = message;
    toast.className = 'toast ' + type;
    toastTimer = setTimeout(() => {
      toast.classList.add('hidden');
    }, 3000);
  }

  // ── Step Navigation ──────────────────────────────────────────────────────
  function goToStep(step) {
    state.currentStep = step;
    steps.forEach((el) => {
      const s = parseInt(el.dataset.step);
      el.classList.remove('active', 'completed');
      if (s < step) el.classList.add('completed');
      if (s === step) el.classList.add('active');
    });
    Object.values(panels).forEach((p) => p.classList.remove('active'));
    if (panels[step]) panels[step].classList.add('active');

    // Scroll to panel
    if (panels[step]) {
      panels[step].scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  }

  // ── Step 1: CSV Upload ──────────────────────────────────────────────────
  function initUpload() {
    // Click to open file dialog
    uploadZone.addEventListener('click', () => fileInput.click());
    uploadZone.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        fileInput.click();
      }
    });

    fileInput.addEventListener('change', (e) => {
      if (e.target.files.length > 0) {
        handleFile(e.target.files[0]);
      }
    });

    // Drag & drop
    uploadZone.addEventListener('dragover', (e) => {
      e.preventDefault();
      uploadZone.classList.add('drag-over');
    });
    uploadZone.addEventListener('dragleave', () => {
      uploadZone.classList.remove('drag-over');
    });
    uploadZone.addEventListener('drop', (e) => {
      e.preventDefault();
      uploadZone.classList.remove('drag-over');
      const file = e.dataTransfer.files[0];
      if (file) handleFile(file);
    });

    btnChangeFile.addEventListener('click', () => {
      fileInput.click();
    });
  }

  async function handleFile(file) {
    // Validate
    const validExts = ['.csv', '.tsv', '.txt'];
    const ext = '.' + file.name.split('.').pop().toLowerCase();
    const validMimes = ['text/csv', 'text/tab-separated-values', 'text/plain', 'application/vnd.ms-excel'];

    uploadError.classList.add('hidden');
    uploadError.textContent = '';

    if (file.size > 10 * 1024 * 1024) {
      showUploadError('Il file supera i 10 MB. Riduci le dimensioni e riprova.');
      return;
    }

    const formData = new FormData();
    formData.append('file', file);
    formData.append('delimiter', 'auto');

    try {
      const resp = await fetch('api/upload', { method: 'POST', body: formData });
      if (!resp.ok) {
        const err = await resp.json();
        showUploadError(err.error || 'Errore durante il caricamento.');
        return;
      }

      const data = await resp.json();
      state.jobId = data.job_id;
      state.csvHeaders = data.headers;
      state.csvRowCount = data.rowCount;
      state.mapping = {};

      // Render preview table
      renderPreview(data.headers, data.preview);

      // Show preview
      csvPreview.classList.remove('hidden');
      uploadZone.querySelector('.upload-zone-inner').style.display = 'none';

      // Enable next step
      goToStep(2);
      showToast(`${data.rowCount} righe rilevate, ${data.headers.length} colonne`, 'success');

    } catch (err) {
      showUploadError('Errore di rete: ' + err.message);
    }
  }

  function showUploadError(msg) {
    uploadError.textContent = msg;
    uploadError.classList.remove('hidden');
  }

  function renderPreview(headers, rows) {
    rowCountDisplay.textContent = `(${state.csvRowCount} righe, ${headers.length} colonne)`;

    // Thead
    let thead = '<tr>';
    thead += '<th>#</th>';
    headers.forEach((h) => { thead += `<th>${escapeHtml(h)}</th>`; });
    thead += '</tr>';
    previewTable.querySelector('thead').innerHTML = thead;

    // Tbody
    let tbody = '';
    rows.forEach((row, i) => {
      tbody += '<tr>';
      tbody += `<td class="row-num">${i + 1}</td>`;
      headers.forEach((h) => {
        tbody += `<td>${escapeHtml(row[h] || '')}</td>`;
      });
      tbody += '</tr>';
    });
    previewTable.querySelector('tbody').innerHTML = tbody;
  }

  function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  // ── Step 2: Context Selection ────────────────────────────────────────────
  async function loadContexts() {
    try {
      const resp = await fetch('api/contexts');
      if (!resp.ok) throw new Error('Errore nel caricamento contesti');
      const data = await resp.json();
      renderContextCards(data.contexts);
    } catch (err) {
      contextError.textContent = 'Impossibile caricare i contesti predefiniti. Ricarica la pagina.';
      contextError.classList.remove('hidden');
    }
  }

  function renderContextCards(contexts) {
    contextGrid.innerHTML = '';

    contexts.forEach((ctx) => {
      const card = document.createElement('div');
      card.className = 'context-card';
      card.setAttribute('role', 'radio');
      card.setAttribute('aria-checked', 'false');
      card.tabIndex = 0;
      card.dataset.contextId = ctx.id;

      card.innerHTML = `
        <div class="context-card-name">${escapeHtml(ctx.label)}</div>
        <div class="context-card-url">${escapeHtml(ctx.contextUrl)}</div>
        <div class="context-card-desc">${escapeHtml(ctx.description)}</div>
        <div class="context-card-meta">
          <span class="prop-count">${ctx.properties.length} proprietà</span>
          <span>${ctx.commonTypes.length} tipi</span>
        </div>
      `;

      card.addEventListener('click', () => selectContext(ctx, card));
      card.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          selectContext(ctx, card);
        }
      });

      contextGrid.appendChild(card);
    });
  }

  function selectContext(ctx, cardEl) {
    // Deselect all
    contextGrid.querySelectorAll('.context-card').forEach((c) => {
      c.classList.remove('selected');
      c.setAttribute('aria-checked', 'false');
    });
    customContextName.textContent = '';
    customContextFile.value = '';

    // Select
    cardEl.classList.add('selected');
    cardEl.setAttribute('aria-checked', 'true');
    state.selectedContext = {
      id: ctx.id,
      label: ctx.label,
      properties: ctx.properties,
      commonTypes: ctx.commonTypes,
      contextUrl: ctx.contextUrl,
      raw: null,
      isCustom: false,
    };

    // Update step 3
    updateMappingEditor();
    updateEntityTypeSuggestions();
    goToStep(3);
    showToast(`Contesto "${ctx.label}" selezionato — ${ctx.properties.length} proprietà disponibili`, 'success');
  }

  function initCustomContext() {
    customContextFile.addEventListener('change', async (e) => {
      const file = e.target.files[0];
      if (!file) return;

      contextError.classList.add('hidden');
      const formData = new FormData();
      formData.append('file', file);

      try {
        const resp = await fetch('api/context/upload', { method: 'POST', body: formData });
        if (!resp.ok) {
          const err = await resp.json();
          contextError.textContent = err.error || 'Contesto non valido';
          contextError.classList.remove('hidden');
          return;
        }

        const data = await resp.json();

        // Deselect predefined
        contextGrid.querySelectorAll('.context-card').forEach((c) => {
          c.classList.remove('selected');
          c.setAttribute('aria-checked', 'false');
        });

        customContextName.textContent = `✓ ${escapeHtml(data.label)} (${data.properties.length} proprietà)`;

        state.selectedContext = {
          id: 'custom',
          label: data.label,
          properties: data.properties,
          commonTypes: data.commonTypes || [],
          contextUrl: '',
          raw: data.rawContext,
          isCustom: true,
        };

        updateMappingEditor();
        updateEntityTypeSuggestions();
        goToStep(3);
        showToast(`Contesto personalizzato caricato — ${data.properties.length} proprietà`, 'success');

      } catch (err) {
        contextError.textContent = 'Errore di rete: ' + err.message;
        contextError.classList.remove('hidden');
      }
    });

    // Trigger file dialog
    const customBtn = document.querySelector('label[for="custom-context-file"]');
    if (customBtn) {
      customBtn.addEventListener('click', (e) => {
        e.preventDefault();
        customContextFile.click();
      });
    }
  }

  // ── Step 3: Mapping Editor ───────────────────────────────────────────────
  function updateEntityTypeSuggestions() {
    entityTypeSuggestions.innerHTML = '';
    const types = state.selectedContext?.commonTypes || [];
    types.forEach((t) => {
      const opt = document.createElement('option');
      opt.value = t;
      entityTypeSuggestions.appendChild(opt);
    });
  }

  function updateMappingEditor() {
    if (!state.csvHeaders.length || !state.selectedContext) {
      mappingEmpty.classList.remove('hidden');
      mappingList.classList.add('hidden');
      return;
    }

    mappingEmpty.classList.add('hidden');
    mappingList.classList.remove('hidden');
    mappingList.innerHTML = '';

    const properties = state.selectedContext.properties;

    state.csvHeaders.forEach((header) => {
      const currentMapping = state.mapping[header] || { property: '', datatype: 'string' };

      const row = document.createElement('div');
      row.className = 'mapping-row' + (currentMapping.property ? ' mapped' : '');

      row.innerHTML = `
        <div class="mapping-connector" aria-hidden="true">
          <svg width="28" height="28" viewBox="0 0 28 28" fill="none">
            <circle cx="6" cy="14" r="4" fill="#6C5CE7" opacity="0.7"/>
            <circle cx="22" cy="14" r="4" fill="#00CEC9" opacity="0.7"/>
            <line x1="10" y1="14" x2="18" y2="14" stroke="#A29BFE" stroke-width="1.5" stroke-dasharray="3 2" class="connector-line"/>
          </svg>
        </div>
        <div class="mapping-column-name">${escapeHtml(header)}</div>
        <span class="mapping-arrow" aria-hidden="true">→</span>
        <div class="mapping-selects">
          <select class="select-input mapping-property-select" data-column="${escapeHtml(header)}" aria-label="Proprietà per colonna ${escapeHtml(header)}">
            <option value="">-- non mappare --</option>
            ${properties.map((p) => `
              <option value="${escapeHtml(p.name)}" ${currentMapping.property === p.name ? 'selected' : ''}>
                ${escapeHtml(p.name)}
              </option>
            `).join('')}
          </select>
          <select class="select-input mapping-datatype-select" data-column="${escapeHtml(header)}" aria-label="Tipo dato per colonna ${escapeHtml(header)}">
            <option value="string" ${currentMapping.datatype === 'string' ? 'selected' : ''}>stringa</option>
            <option value="integer" ${currentMapping.datatype === 'integer' ? 'selected' : ''}>intero</option>
            <option value="float" ${currentMapping.datatype === 'float' ? 'selected' : ''}>decimale</option>
            <option value="boolean" ${currentMapping.datatype === 'boolean' ? 'selected' : ''}>booleano</option>
            <option value="date" ${currentMapping.datatype === 'date' ? 'selected' : ''}>data</option>
            <option value="url" ${currentMapping.datatype === 'url' ? 'selected' : ''}>URL</option>
          </select>
        </div>
      `;

      mappingList.appendChild(row);

      // Event listeners
      const propSelect = row.querySelector('.mapping-property-select');
      const typeSelect = row.querySelector('.mapping-datatype-select');

      propSelect.addEventListener('change', () => {
        handleMappingChange(header, propSelect.value, typeSelect.value, row);
      });
      typeSelect.addEventListener('change', () => {
        handleMappingChange(header, propSelect.value, typeSelect.value, row);
      });
    });

    updateConvertButton();
  }

  function handleMappingChange(column, property, datatype, rowEl) {
    if (property) {
      state.mapping[column] = { property, datatype };
      rowEl.classList.add('mapped');
    } else {
      delete state.mapping[column];
      rowEl.classList.remove('mapped');
    }
    updateConvertButton();
  }

  function updateConvertButton() {
    const hasMappings = Object.keys(state.mapping).length > 0;
    btnConvert.disabled = !hasMappings || !state.jobId;
  }

  // Listen to entity type and base IRI changes
  function initMappingListeners() {
    entityTypeInput.addEventListener('input', () => {
      state.entityType = entityTypeInput.value.trim();
    });
    baseIriInput.addEventListener('input', () => {
      state.baseIri = baseIriInput.value.trim();
    });
  }

  // ── Step 4: Conversion ───────────────────────────────────────────────────
  async function startConversion() {
    if (!state.jobId) {
      showToast('Carica prima un file CSV', 'error');
      return;
    }
    if (Object.keys(state.mapping).length === 0) {
      showToast('Mappa almeno una colonna a una proprietà', 'error');
      return;
    }

    // Gather context data
    let contextData = null;
    if (state.selectedContext) {
      if (state.selectedContext.raw) {
        contextData = state.selectedContext.raw;
      } else {
        // For predefined contexts, we need to fetch the raw context
        // The server will load it from the file
        contextData = { contextId: state.selectedContext.id };
      }
    }

    const payload = {
      job_id: state.jobId,
      context: contextData,
      mapping: state.mapping,
      entity_type: state.entityType || '',
      base_iri: state.baseIri || '',
    };

    // Show progress
    progressArea.classList.remove('hidden');
    resultArea.classList.add('hidden');
    convertError.classList.add('hidden');
    btnConvert.disabled = true;
    updateProgress(0, 'Avvio conversione...');

    try {
      const resp = await fetch('api/convert', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      if (!resp.ok) {
        const err = await resp.json();
        throw new Error(err.error || 'Errore nella conversione');
      }

      const data = await resp.json();
      updateProgress(5, 'Conversione in corso...');

      // Poll for completion
      pollJobStatus(data.job_id);

    } catch (err) {
      updateProgress(0, '');
      progressArea.classList.add('hidden');
      btnConvert.disabled = false;
      convertError.textContent = err.message;
      convertError.classList.remove('hidden');
      showToast('Conversione fallita: ' + err.message, 'error');
    }
  }

  function pollJobStatus(jobId) {
    if (state.pollingTimer) clearInterval(state.pollingTimer);

    state.pollingTimer = setInterval(async () => {
      try {
        const resp = await fetch(`api/job/${jobId}`);
        if (!resp.ok) throw new Error('Errore nel controllo stato');

        const data = await resp.json();

        if (data.status === 'completed') {
          clearInterval(state.pollingTimer);
          state.pollingTimer = null;
          updateProgress(100, 'Completato!');
          await showResult(jobId);
          btnConvert.disabled = false;
          showToast('JSON-LD generato con successo', 'success');
        } else if (data.status === 'error') {
          clearInterval(state.pollingTimer);
          state.pollingTimer = null;
          updateProgress(0, '');
          progressArea.classList.add('hidden');
          btnConvert.disabled = false;
          convertError.textContent = data.error || 'Errore sconosciuto';
          convertError.classList.remove('hidden');
          showToast('Errore: ' + (data.error || 'sconosciuto'), 'error');
        } else if (data.status === 'processing') {
          updateProgress(data.progress || 50, 'Elaborazione in corso...');
        } else if (data.status === 'queued') {
          updateProgress(data.progress || 5, 'In coda...');
        }
      } catch (err) {
        clearInterval(state.pollingTimer);
        state.pollingTimer = null;
        btnConvert.disabled = false;
        showToast('Errore di polling: ' + err.message, 'error');
      }
    }, 500);
  }

  function updateProgress(pct, status) {
    progressFill.style.width = pct + '%';
    progressTextEl.textContent = pct + '%';
    progressFill.parentElement.setAttribute('aria-valuenow', pct);
    if (status) progressStatus.textContent = status;
  }

  async function showResult(jobId) {
    try {
      const resp = await fetch(`api/preview/${jobId}`);
      if (!resp.ok) throw new Error('Risultato non disponibile');
      const data = await resp.json();

      // Pretty print JSON
      const jsonStr = JSON.stringify(data, null, 2);
      jsonldOutput.textContent = jsonStr;

      // Apply basic syntax highlighting
      highlightJson(jsonldOutput);

      resultArea.classList.remove('hidden');

      // Show validation
      // Fetch job status for validation info
      const jobResp = await fetch(`api/job/${jobId}`);
      if (jobResp.ok) {
        const jobData = await jobResp.json();
        if (jobData.validation) {
          const v = jobData.validation;
          let msg = `${v.entityCount} entità generate da ${v.totalRows} righe. `;

          if (v.warnings && v.warnings.length > 0) {
            validationInfo.className = 'validation-info warning';
            msg += v.warnings.join(' ');
          } else {
            validationInfo.className = 'validation-info success';
            msg += 'Validazione completata senza errori.';
          }
          validationInfo.textContent = msg;
          validationInfo.classList.remove('hidden');
        }
      }

    } catch (err) {
      showToast('Errore nel caricamento risultato: ' + err.message, 'error');
    }
  }

  function highlightJson(codeEl) {
    // Simple syntax highlighting for JSON in the code block
    const text = codeEl.textContent;
    const highlighted = text.replace(
      /("(?:[^"\\]|\\.)*")\s*:/g,
      '<span class="key">$1</span>:'
    ).replace(
      /:\s*("(?:[^"\\]|\\.)*")/g,
      ': <span class="str">$1</span>'
    ).replace(
      /:\s*(\d+\.?\d*)/g,
      ': <span class="num">$1</span>'
    ).replace(
      /:\s*(true|false|null)/g,
      ': <span class="bool">$1</span>'
    );
    codeEl.innerHTML = highlighted;
  }

  function initDownload() {
    btnDownload.addEventListener('click', () => {
      if (!state.jobId) return;
      // Create a download link
      const a = document.createElement('a');
      a.href = `api/download/${state.jobId}`;
      a.download = 'output.jsonld';
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      showToast('Download avviato', 'success');
    });
  }

  function initCopy() {
    btnCopy.addEventListener('click', async () => {
      const text = jsonldOutput.textContent;
      try {
        await navigator.clipboard.writeText(text);
        showToast('Copiato negli appunti', 'success');
      } catch {
        // Fallback
        const textarea = document.createElement('textarea');
        textarea.value = text;
        document.body.appendChild(textarea);
        textarea.select();
        document.execCommand('copy');
        document.body.removeChild(textarea);
        showToast('Copiato negli appunti', 'success');
      }
    });
  }

  // ── Init ─────────────────────────────────────────────────────────────────
  function init() {
    initUpload();
    initCustomContext();
    initMappingListeners();
    initDownload();
    initCopy();

    btnConvert.addEventListener('click', startConversion);

    // Load contexts on page load
    loadContexts();

    // Keyboard navigation for steps
    document.addEventListener('keydown', (e) => {
      // Allow navigation between steps with Ctrl+number
      if (e.ctrlKey && e.key >= '1' && e.key <= '4') {
        e.preventDefault();
        const step = parseInt(e.key);
        if (step === 1 || (step > 1 && state.jobId)) {
          goToStep(step);
        }
      }
    });
  }

  // Start
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

})();

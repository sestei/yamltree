(function renderTree() {
  var treeData = window.__TREE_DATA__;
  if (!treeData) return;

  var container = document.getElementById("tree-container");
  var columnsEl = document.getElementById("columns");
  var svg = document.getElementById("connectors");
  var svgNS = "http://www.w3.org/2000/svg";

  // path[d - 1] holds the selected card in column d (columns are 1-indexed;
  // column 0 is always just the root, which has no "selected" state of its own).
  var path = [];

  // JSON-stringified `_path` of the card currently showing an edit form, if any.
  var editingPath = null;

  // True while the card in `editingPath` is a freshly inserted card that has
  // never been saved — cancelling out of it with no changes made deletes it
  // instead of just leaving the "New Card" stub behind.
  var editingIsFreshInsert = false;

  function hasChildren(card) {
    return Array.isArray(card.subcards) && card.subcards.length > 0;
  }

  function findByPath(fullPath) {
    var node = treeData;
    for (var i = 0; i < fullPath.length; i++) {
      if (!node.subcards || !node.subcards[fullPath[i]]) return null;
      node = node.subcards[fullPath[i]];
    }
    return node;
  }

  function trlColorFor(n) {
    var hue = ((n - 1) / 8) * 120;
    return "hsl(" + hue.toFixed(1) + ", 55%, 34%)";
  }

  // ---- persistence across the reload every mutation (and the mtime poll) causes ----

  function focusChainFromPath(fullPath) {
    return fullPath.map(function (_, i) {
      return fullPath.slice(0, i + 1);
    });
  }

  function currentSelectionChain() {
    return path
      .filter(function (c) {
        return !!c;
      })
      .map(function (c) {
        return c._path;
      });
  }

  function saveSelection() {
    sessionStorage.setItem("yamltree.selection", JSON.stringify(currentSelectionChain()));
  }
  window.__yamltreeSaveSelection = saveSelection;

  function reloadWithFocus(fullPath, openEditAfter) {
    var chain = fullPath ? focusChainFromPath(fullPath) : currentSelectionChain();
    sessionStorage.setItem("yamltree.selection", JSON.stringify(chain));
    if (fullPath && openEditAfter) {
      sessionStorage.setItem("yamltree.editAfter", JSON.stringify(fullPath));
    } else {
      sessionStorage.removeItem("yamltree.editAfter");
    }
    location.reload();
  }

  // ---- server calls ----

  function postJSON(url, payload) {
    return fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }).then(function (res) {
      return res.json().then(function (data) {
        if (!res.ok) throw new Error(data.error || "Request failed (" + res.status + ")");
        return data;
      });
    });
  }

  function moveCard(card, direction) {
    postJSON("/api/cards/move", { path: card._path, direction: direction })
      .then(function (data) {
        reloadWithFocus(data.path, false);
      })
      .catch(function (err) {
        alert(err.message);
      });
  }

  function insertCard(card, kind) {
    postJSON("/api/cards/insert", { path: card._path, kind: kind })
      .then(function (data) {
        reloadWithFocus(data.path, true);
      })
      .catch(function (err) {
        alert(err.message);
      });
  }

  function deleteUnsavedCard(card) {
    postJSON("/api/cards/delete", { path: card._path })
      .then(function () {
        editingPath = null;
        editingIsFreshInsert = false;
        reloadWithFocus(card._path.slice(0, -1), false);
      })
      .catch(function (err) {
        alert(err.message);
      });
  }

  function archiveCard(card) {
    if (!confirm('Archive "' + card.title + '"? It will be removed from the tree (recoverable by hand-editing main.yaml).')) {
      return;
    }
    postJSON("/api/cards/archive", { path: card._path })
      .then(function () {
        reloadWithFocus(null, false);
      })
      .catch(function (err) {
        alert(err.message);
      });
  }

  // ---- rendering ----

  function archiveIcon() {
    var svg = document.createElementNS(svgNS, "svg");
    svg.setAttribute("viewBox", "0 0 16 16");
    svg.setAttribute("width", "13");
    svg.setAttribute("height", "13");
    svg.setAttribute("class", "icon-svg");

    var lid = document.createElementNS(svgNS, "rect");
    lid.setAttribute("x", "1.5");
    lid.setAttribute("y", "2.5");
    lid.setAttribute("width", "13");
    lid.setAttribute("height", "3");
    lid.setAttribute("rx", "0.6");
    lid.setAttribute("fill", "none");
    lid.setAttribute("stroke", "currentColor");
    lid.setAttribute("stroke-width", "1.3");
    svg.appendChild(lid);

    var box = document.createElementNS(svgNS, "rect");
    box.setAttribute("x", "2.5");
    box.setAttribute("y", "6.5");
    box.setAttribute("width", "11");
    box.setAttribute("height", "7");
    box.setAttribute("rx", "0.6");
    box.setAttribute("fill", "none");
    box.setAttribute("stroke", "currentColor");
    box.setAttribute("stroke-width", "1.3");
    svg.appendChild(box);

    var handle = document.createElementNS(svgNS, "line");
    handle.setAttribute("x1", "6.5");
    handle.setAttribute("y1", "9.7");
    handle.setAttribute("x2", "9.5");
    handle.setAttribute("y2", "9.7");
    handle.setAttribute("stroke", "currentColor");
    handle.setAttribute("stroke-width", "1.3");
    svg.appendChild(handle);

    return svg;
  }

  function actionButton(content, title, extraClass, onClick) {
    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "card-action-btn icon-btn" + (extraClass ? " " + extraClass : "");
    if (typeof content === "string") {
      btn.textContent = content;
    } else {
      btn.appendChild(content);
    }
    btn.title = title;
    btn.addEventListener("click", function (evt) {
      evt.stopPropagation();
      onClick();
    });
    return btn;
  }

  function buildActionsRow(card) {
    var row = document.createElement("div");
    row.className = "card-actions";
    var isRoot = card._path.length === 0;

    if (!isRoot) {
      row.appendChild(
        actionButton("▲", "Move up", "", function () {
          moveCard(card, "up");
        })
      );
      row.appendChild(
        actionButton("▼", "Move down", "", function () {
          moveCard(card, "down");
        })
      );
    }

    row.appendChild(
      actionButton("✎", "Edit", "", function () {
        editingPath = JSON.stringify(card._path);
        editingIsFreshInsert = false;
        render();
      })
    );

    if (!isRoot) {
      row.appendChild(
        actionButton("+", "Insert card at this level", "", function () {
          insertCard(card, "sibling");
        })
      );
    }

    if (!hasChildren(card)) {
      row.appendChild(
        actionButton("+❯", "Add first child card", "", function () {
          insertCard(card, "child");
        })
      );
    }

    if (!isRoot) {
      row.appendChild(
        actionButton(archiveIcon(), "Archive", "danger", function () {
          archiveCard(card);
        })
      );
    }

    return row;
  }

  function buildEditForm(card) {
    var isFreshInsert = editingIsFreshInsert;

    var el = document.createElement("div");
    el.className = "card editing";

    var form = document.createElement("div");
    form.className = "card-edit-form";
    el.appendChild(form);

    var titleInput = document.createElement("input");
    titleInput.type = "text";
    titleInput.className = "edit-title-input";
    titleInput.value = card.title || "";
    titleInput.placeholder = "Title";
    form.appendChild(titleInput);

    var statusRow = document.createElement("div");
    statusRow.className = "trl-picker";
    form.appendChild(statusRow);

    var selectedTrl = card.trl || null;
    var trlButtons = [];
    for (var n = 1; n <= 9; n++) {
      (function (n) {
        var b = document.createElement("button");
        b.type = "button";
        b.className = "trl-picker-btn" + (n === selectedTrl ? " active" : "");
        b.textContent = String(n);
        b.style.setProperty("--trl-color", trlColorFor(n));
        b.addEventListener("click", function () {
          selectedTrl = selectedTrl === n ? null : n;
          trlButtons.forEach(function (btn, i) {
            btn.classList.toggle("active", i + 1 === selectedTrl);
          });
        });
        statusRow.appendChild(b);
        trlButtons.push(b);
      })(n);
    }

    var isImportant = !!card.important;
    var importantBtn = document.createElement("button");
    importantBtn.type = "button";
    importantBtn.className = "important-toggle-btn" + (isImportant ? " active" : "");
    importantBtn.textContent = "★";
    importantBtn.title = "Mark important";
    importantBtn.addEventListener("click", function () {
      isImportant = !isImportant;
      importantBtn.classList.toggle("active", isImportant);
    });
    statusRow.appendChild(importantBtn);

    var contactsWrap = document.createElement("div");
    contactsWrap.className = "contact-edit-rows";
    form.appendChild(contactsWrap);

    function addContactRow(existing) {
      var row = document.createElement("div");
      row.className = "contact-edit-row";

      var nameInput = document.createElement("input");
      nameInput.type = "text";
      nameInput.className = "contact-name-input";
      nameInput.placeholder = "Name";
      nameInput.value = (existing && existing.name) || "";

      var emailInput = document.createElement("input");
      emailInput.type = "text";
      emailInput.className = "contact-email-input";
      emailInput.placeholder = "Email";
      emailInput.value = (existing && existing.email) || "";

      var instInput = document.createElement("input");
      instInput.type = "text";
      instInput.className = "contact-institution-input";
      instInput.placeholder = "Institution";
      instInput.value = (existing && existing.institution) || "";

      row.appendChild(nameInput);
      row.appendChild(emailInput);
      row.appendChild(instInput);
      contactsWrap.appendChild(row);

      nameInput.addEventListener("input", function () {
        var rows = contactsWrap.querySelectorAll(".contact-edit-row");
        var lastRow = rows[rows.length - 1];
        if (row === lastRow && nameInput.value.trim()) {
          addContactRow(null);
        }
      });
    }

    (card.contacts || []).forEach(function (c) {
      addContactRow(c);
    });
    addContactRow(null);

    var descArea = document.createElement("textarea");
    descArea.className = "edit-description-input";
    descArea.value = card.description || "";
    descArea.placeholder = "Description (Markdown supported)";
    form.appendChild(descArea);

    var actions = document.createElement("div");
    actions.className = "card-edit-actions";
    form.appendChild(actions);

    function collectContacts() {
      var contacts = [];
      contactsWrap.querySelectorAll(".contact-edit-row").forEach(function (row) {
        var inputs = row.querySelectorAll("input");
        var name = inputs[0].value.trim();
        if (!name) return;
        contacts.push({
          name: name,
          email: inputs[1].value.trim(),
          institution: inputs[2].value.trim(),
        });
      });
      return contacts;
    }

    function isPristine() {
      return (
        titleInput.value.trim() === (card.title || "").trim() &&
        descArea.value === (card.description || "") &&
        collectContacts().length === (card.contacts || []).length &&
        selectedTrl === (card.trl || null) &&
        isImportant === !!card.important
      );
    }

    var saveBtn = document.createElement("button");
    saveBtn.type = "button";
    saveBtn.className = "card-action-btn primary";
    saveBtn.textContent = "Save";
    saveBtn.addEventListener("click", function () {
      postJSON("/api/cards/edit", {
        path: card._path,
        title: titleInput.value,
        description: descArea.value,
        contacts: collectContacts(),
        trl: selectedTrl,
        important: isImportant,
      })
        .then(function () {
          editingPath = null;
          editingIsFreshInsert = false;
          reloadWithFocus(card._path, false);
        })
        .catch(function (err) {
          alert(err.message);
        });
    });

    var cancelBtn = document.createElement("button");
    cancelBtn.type = "button";
    cancelBtn.className = "card-action-btn";
    cancelBtn.textContent = "Cancel";
    cancelBtn.addEventListener("click", function () {
      if (isFreshInsert && isPristine()) {
        deleteUnsavedCard(card);
        return;
      }
      editingPath = null;
      editingIsFreshInsert = false;
      render();
    });

    actions.appendChild(saveBtn);
    actions.appendChild(cancelBtn);

    return el;
  }

  function buildCardEl(card, isSelected, interactive, columnIndex) {
    if (editingPath === JSON.stringify(card._path)) {
      return buildEditForm(card);
    }

    var el = document.createElement("div");
    var classes = ["card"];
    if (isSelected) classes.push("selected");
    if (hasChildren(card)) classes.push("has-children");
    if (card.trl) classes.push("has-trl");
    if (card.important) {
      classes.push("important");
    } else if (card.has_important) {
      classes.push("important-descendant");
    }
    el.className = classes.join(" ");
    if (card.trl_color) {
      el.style.setProperty("--trl-color", card.trl_color);
    }

    var header = document.createElement("div");
    header.className = "card-header";

    if (card.important) {
      var flag = document.createElement("span");
      flag.className = "card-flag";
      flag.textContent = "★";
      flag.title = "Important";
      header.appendChild(flag);
    }

    var title = document.createElement("span");
    title.className = "card-title";
    title.textContent = card.title;
    title.addEventListener("dblclick", function (evt) {
      evt.stopPropagation();
      editingPath = JSON.stringify(card._path);
      editingIsFreshInsert = false;
      render();
    });
    header.appendChild(title);

    if (card.trl) {
      var badge = document.createElement("span");
      badge.className = "card-trl-badge";
      badge.textContent = "TRL " + card.trl;
      header.appendChild(badge);
    }

    if (hasChildren(card)) {
      var toggle = document.createElement("span");
      toggle.className = "card-toggle";
      toggle.textContent = "❯";
      header.appendChild(toggle);
      if (interactive) {
        header.addEventListener("click", function () {
          selectAt(columnIndex, card);
        });
      }
    }

    el.appendChild(header);

    if (card.contacts && card.contacts.length) {
      var list = document.createElement("ul");
      list.className = "card-contacts";
      card.contacts.forEach(function (contact) {
        var li = document.createElement("li");

        var name = document.createElement("span");
        name.className = "contact-name";
        name.textContent = contact.name;
        li.appendChild(name);

        if (contact.institution) {
          var inst = document.createElement("span");
          inst.className = "contact-institution";
          inst.textContent = contact.institution;
          li.appendChild(inst);
        }

        if (contact.email) {
          var mail = document.createElement("a");
          mail.className = "contact-email";
          mail.href = "mailto:" + contact.email;
          mail.textContent = contact.email;
          li.appendChild(mail);
        }

        list.appendChild(li);
      });
      el.appendChild(list);
    }

    if (card.description_html) {
      var desc = document.createElement("div");
      desc.className = "card-description";
      desc.innerHTML = card.description_html;
      el.appendChild(desc);
    }

    el.appendChild(buildActionsRow(card));

    return el;
  }

  function selectAt(depth, card) {
    if (path[depth - 1] === card) {
      path = path.slice(0, depth - 1);
    } else {
      path = path.slice(0, depth - 1);
      path[depth - 1] = card;
    }
    render();
  }

  function render() {
    columnsEl.innerHTML = "";

    var rootColumn = document.createElement("div");
    rootColumn.className = "tree-column";
    rootColumn.appendChild(buildCardEl(treeData, false, false, 0));
    columnsEl.appendChild(rootColumn);

    var parent = treeData;
    var depth = 1;
    while (parent && hasChildren(parent)) {
      var selected = path[depth - 1];
      var column = document.createElement("div");
      column.className = "tree-column";
      parent.subcards.forEach(function (child) {
        column.appendChild(buildCardEl(child, child === selected, true, depth));
      });
      columnsEl.appendChild(column);
      if (!selected) break;
      parent = selected;
      depth++;
    }

    requestAnimationFrame(drawConnectors);

    if (editingPath) {
      var titleInputToFocus = columnsEl.querySelector(".edit-title-input");
      if (titleInputToFocus) {
        titleInputToFocus.focus();
        titleInputToFocus.select();
      }
    }
  }

  function drawConnectors() {
    while (svg.firstChild) svg.removeChild(svg.firstChild);

    var containerRect = container.getBoundingClientRect();
    var contentWidth = columnsEl.scrollWidth;
    var contentHeight = columnsEl.scrollHeight;
    svg.setAttribute("width", contentWidth);
    svg.setAttribute("height", contentHeight);

    var cols = columnsEl.querySelectorAll(".tree-column");
    for (var i = 0; i < cols.length - 1; i++) {
      // column 0 (the root) always connects to its children column; every
      // later column only connects onward through whichever card is selected.
      var selectedCard = i === 0 ? cols[i].querySelector(".card") : cols[i].querySelector(".card.selected");
      if (!selectedCard) continue;

      var fromRect = selectedCard.getBoundingClientRect();
      var fromX = fromRect.right - containerRect.left + container.scrollLeft;
      var fromY = fromRect.top + fromRect.height / 2 - containerRect.top + container.scrollTop;

      var childCards = cols[i + 1].querySelectorAll(".card");
      childCards.forEach(function (childEl) {
        var toRect = childEl.getBoundingClientRect();
        var toX = toRect.left - containerRect.left + container.scrollLeft;
        var toY = toRect.top + toRect.height / 2 - containerRect.top + container.scrollTop;
        var midX = (fromX + toX) / 2;

        var line = document.createElementNS(svgNS, "path");
        var d = "M " + fromX + " " + fromY +
          " L " + midX + " " + fromY +
          " L " + midX + " " + toY +
          " L " + toX + " " + toY;
        line.setAttribute("d", d);
        line.setAttribute("class", "connector-line");
        svg.appendChild(line);
      });
    }
  }

  window.addEventListener("resize", function () {
    requestAnimationFrame(drawConnectors);
  });
  container.addEventListener("scroll", function () {
    requestAnimationFrame(drawConnectors);
  });

  // ---- restore selection (and any pending edit-after-insert) from before the last reload ----

  var restoredChain = null;
  var editAfterPath = null;
  try {
    restoredChain = JSON.parse(sessionStorage.getItem("yamltree.selection") || "null");
  } catch (e) {
    restoredChain = null;
  }
  try {
    editAfterPath = JSON.parse(sessionStorage.getItem("yamltree.editAfter") || "null");
  } catch (e) {
    editAfterPath = null;
  }
  sessionStorage.removeItem("yamltree.selection");
  sessionStorage.removeItem("yamltree.editAfter");

  if (restoredChain) {
    var restored = [];
    for (var d = 0; d < restoredChain.length; d++) {
      var node = findByPath(restoredChain[d]);
      if (!node) break;
      restored[d] = node;
    }
    path = restored;
  }

  if (editAfterPath) {
    var editNode = findByPath(editAfterPath);
    if (editNode) {
      editingPath = JSON.stringify(editAfterPath);
      editingIsFreshInsert = true;
    }
  }

  render();
})();

(function pollForChanges() {
  var initialMtime = parseFloat(document.body.dataset.mtime);
  if (isNaN(initialMtime)) return;

  setInterval(function () {
    fetch("/api/mtime")
      .then(function (res) {
        return res.json();
      })
      .then(function (data) {
        if (Math.abs(data.mtime - initialMtime) > 0.001) {
          if (typeof window.__yamltreeSaveSelection === "function") {
            window.__yamltreeSaveSelection();
          }
          location.reload();
        }
      })
      .catch(function () {
        /* server may be mid-restart; ignore and retry next poll */
      });
  }, 2000);
})();

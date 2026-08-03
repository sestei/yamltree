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

  function hasChildren(card) {
    return Array.isArray(card.subcards) && card.subcards.length > 0;
  }

  function buildCardEl(card, isSelected, interactive, columnIndex) {
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
          location.reload();
        }
      })
      .catch(function () {
        /* server may be mid-restart; ignore and retry next poll */
      });
  }, 2000);
})();

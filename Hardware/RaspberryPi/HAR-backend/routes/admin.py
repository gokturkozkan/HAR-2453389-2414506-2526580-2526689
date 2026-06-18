from flask import Blueprint, request, jsonify
from database import db_all
import os
import json
import html

admin_bp = Blueprint("admin", __name__)

NODE_NAMES = {
    1: "Wrist / Hand",
    2: "Chest",
    3: "Ankle",
}


def admin_guard():
    """Simple guard using ADMIN_TOKEN for dev environments."""
    token_required = os.getenv("ADMIN_TOKEN")

    if not token_required:
        return True

    header_token = request.headers.get("x-admin-token")
    query_token = request.args.get("token", "")

    return header_token == token_required or query_token == token_required


@admin_bp.route("/admin/users.json", methods=["GET"])
def get_users_json():
    if not admin_guard():
        return "Unauthorized", 401

    try:
        users = db_all(
            "SELECT id, username, created_at FROM users ORDER BY created_at DESC LIMIT 100"
        )
        return jsonify(users)
    except Exception:
        return jsonify({"message": "Failed to load users"}), 500


@admin_bp.route("/admin/esp-devices.json", methods=["GET"])
def get_esp_devices_json():
    if not admin_guard():
        return "Unauthorized", 401

    try:
        esps = db_all(
            "SELECT id, is_connected as isConnected "
            "FROM esp_devices "
            "WHERE id IN (1, 2, 3) "
            "ORDER BY id ASC"
        )

        for esp in esps:
            esp["name"] = NODE_NAMES.get(esp["id"], f"Node {esp['id']}")

        return jsonify(esps)

    except Exception:
        return jsonify({"message": "Failed to load esp devices"}), 500


@admin_bp.route("/admin", methods=["GET"])
def admin_page():
    if not admin_guard():
        return "Unauthorized", 401

    try:
        users = db_all(
            "SELECT id, username, created_at FROM users ORDER BY created_at DESC LIMIT 100"
        )

        esps = db_all(
            "SELECT id, is_connected as isConnected "
            "FROM esp_devices "
            "WHERE id IN (1, 2, 3) "
            "ORDER BY id ASC"
        )

        labels = db_all("SELECT id, name FROM labels ORDER BY id ASC")

        relabels = db_all(
            "SELECT id, node_id, original_label, new_label, sensor_data, esp_data, created_at "
            "FROM relabels ORDER BY created_at DESC, id DESC LIMIT 100"
        )

        current_label_query = db_all(
            "SELECT id, name FROM labels ORDER BY id ASC LIMIT 1"
        )
        current_label = current_label_query[0] if current_label_query else None

        def safe_text(value):
            if value is None:
                return ""
            return html.escape(str(value))

        def parse_sensor_data(raw_json):
            """
            Supports the new 3-node PAMAP2-style data.

            Each reading can contain:
            ax, ay, az, gx, gy, gz, mx, my, mz
            """

            if not raw_json:
                return []

            try:
                parsed = json.loads(raw_json)

                if not isinstance(parsed, list):
                    return []

                cleaned = []

                for row in parsed:
                    if not isinstance(row, dict):
                        continue

                    cleaned.append({
                        "ax": row.get("ax", ""),
                        "ay": row.get("ay", ""),
                        "az": row.get("az", ""),
                        "gx": row.get("gx", ""),
                        "gy": row.get("gy", ""),
                        "gz": row.get("gz", ""),
                        "mx": row.get("mx", ""),
                        "my": row.get("my", ""),
                        "mz": row.get("mz", ""),
                    })

                return cleaned

            except Exception:
                return []

        def node_name(node_id):
            try:
                return NODE_NAMES.get(int(node_id), f"Node {node_id}")
            except Exception:
                return ""

        user_rows = "".join([
            (
                f"<tr>"
                f"<td>{safe_text(u['id'])}</td>"
                f"<td>{safe_text(u['username'])}</td>"
                f"<td>{safe_text(u.get('created_at', ''))}</td>"
                f"</tr>"
            )
            for u in users
        ])

        esp_rows = ""

        for e in esps:
            esp_id = e.get("id")
            is_connected = e.get("isConnected")

            if is_connected == 1 or is_connected is True:
                status = '<span class="pill ok">connected</span>'
            elif is_connected == 0 or is_connected is False:
                status = '<span class="pill bad">disconnected</span>'
            else:
                status = '<span class="pill unk">unknown</span>'

            esp_rows += (
                f"<tr>"
                f"<td>{safe_text(esp_id)}</td>"
                f"<td>{safe_text(NODE_NAMES.get(esp_id, 'Unknown'))}</td>"
                f"<td>{status}</td>"
                f"</tr>"
            )

        label_rows = ""

        for label in labels:
            label_rows += (
                f"<tr>"
                f"<td>{safe_text(label['id'])}</td>"
                f"<td>{safe_text(label['name'])}</td>"
                f"</tr>"
            )

        relabel_rows = ""
        modal_payloads = []

        for r in relabels:
            parsed_sensor_data = parse_sensor_data(r.get("sensor_data"))
            modal_id = f"sensor-modal-{r['id']}"

            modal_payloads.append({
                "modal_id": modal_id,
                "rows": parsed_sensor_data,
            })

            sensor_button = (
                f"<button class=\"secondary-btn\" onclick=\"openSensorModal('{modal_id}')\">"
                f"View ({len(parsed_sensor_data)})"
                f"</button>"
            )

            relabel_rows += (
                f"<tr>"
                f"<td>{safe_text(r['id'])}</td>"
                f"<td>{safe_text(r.get('created_at', ''))}</td>"
                f"<td>{safe_text(r.get('node_id', ''))}</td>"
                f"<td>{safe_text(node_name(r.get('node_id')))}</td>"
                f"<td>{safe_text(r.get('original_label', ''))}</td>"
                f"<td>{safe_text(r.get('new_label', ''))}</td>"
                f"<td>{sensor_button}</td>"
                f"</tr>"
            )

        modal_html = ""

        for item in modal_payloads:
            if item["rows"]:
                body_rows = "".join([
                    (
                        f"<tr>"
                        f"<td>{safe_text(row['ax'])}</td>"
                        f"<td>{safe_text(row['ay'])}</td>"
                        f"<td>{safe_text(row['az'])}</td>"
                        f"<td class=\"divider-cell\">|</td>"
                        f"<td>{safe_text(row['gx'])}</td>"
                        f"<td>{safe_text(row['gy'])}</td>"
                        f"<td>{safe_text(row['gz'])}</td>"
                        f"<td class=\"divider-cell\">|</td>"
                        f"<td>{safe_text(row['mx'])}</td>"
                        f"<td>{safe_text(row['my'])}</td>"
                        f"<td>{safe_text(row['mz'])}</td>"
                        f"</tr>"
                    )
                    for row in item["rows"]
                ])
            else:
                body_rows = "<tr><td colspan=\"11\">No sensor data available</td></tr>"

            modal_html += f"""
            <div id="{item['modal_id']}" class="modal-backdrop" onclick="closeIfBackdrop(event, '{item['modal_id']}')">
              <div class="modal-card">
                <div class="modal-header">
                  <h3>Sensor Data</h3>
                  <button class="close-btn" onclick="closeSensorModal('{item['modal_id']}')">&times;</button>
                </div>
                <div class="modal-content">
                  <table>
                    <thead>
                      <tr>
                        <th>accX</th>
                        <th>accY</th>
                        <th>accZ</th>
                        <th></th>
                        <th>gyroX</th>
                        <th>gyroY</th>
                        <th>gyroZ</th>
                        <th></th>
                        <th>magX</th>
                        <th>magY</th>
                        <th>magZ</th>
                      </tr>
                    </thead>
                    <tbody>
                      {body_rows}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
            """

        html_page = f"""<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>HAR Admin</title>
    <style>
      body {{ font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial; margin: 16px; }}
      h1 {{ margin: 0 0 8px 0; }}
      h2 {{ margin-top: 24px; }}
      h3 {{ margin: 0; }}
      table {{ border-collapse: collapse; width: 100%; margin-top: 8px; }}
      th, td {{ border: 1px solid #ddd; padding: 8px; font-size: 14px; }}
      th {{ background: #f7f7f7; text-align: left; }}
      .pill {{ display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 12px; }}
      .ok {{ background: #e7f7ee; color: #0f7a3b; }}
      .bad {{ background: #fdecea; color: #b3261e; }}
      .unk {{ background: #eef2f7; color: #334155; }}
      .grid {{ display: grid; grid-template-columns: 1fr; gap: 24px; }}
      @media (min-width: 900px) {{ .grid {{ grid-template-columns: 1fr 1fr; }} }}
      .tip {{ color: #475569; font-size: 13px; }}
      .header {{ display:flex; align-items:center; justify-content:space-between; }}
      code {{ background:#f3f4f6; padding:2px 6px; border-radius:4px; }}
      .label-section {{ grid-column: 1 / -1; }}
      .label-form {{ display: flex; gap: 8px; margin-top: 8px; }}
      input[type="text"] {{ padding: 8px; border: 1px solid #ddd; border-radius: 4px; flex: 1; }}
      button {{ padding: 8px 16px; background: #0f7a3b; color: white; border: none; border-radius: 4px; cursor: pointer; }}
      button:hover {{ background: #0d6a31; }}
      .secondary-btn {{ background: #2563eb; }}
      .secondary-btn:hover {{ background: #1d4ed8; }}

      .modal-backdrop {{
        display: none;
        position: fixed;
        inset: 0;
        background: rgba(0, 0, 0, 0.45);
        z-index: 9999;
        align-items: center;
        justify-content: center;
        padding: 20px;
      }}

      .modal-backdrop.open {{
        display: flex;
      }}

      .modal-card {{
        background: white;
        width: min(1100px, 95vw);
        max-height: 85vh;
        overflow: auto;
        border-radius: 12px;
        box-shadow: 0 10px 30px rgba(0,0,0,0.2);
        padding: 16px;
      }}

      .modal-header {{
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 12px;
      }}

      .close-btn {{
        background: transparent;
        color: #111827;
        font-size: 24px;
        padding: 0 8px;
      }}

      .close-btn:hover {{
        background: #f3f4f6;
      }}

      .divider-cell {{
        text-align: center;
        font-weight: bold;
        background: #fafafa;
        width: 24px;
      }}
    </style>
  </head>

  <body>
    <div class="header">
      <h1>HAR Admin</h1>
      <div class="tip">Health: <span class="pill ok">ok</span></div>
    </div>

    <div class="tip">
      3-node PAMAP2 setup:
      <code>1 = Wrist</code>,
      <code>2 = Chest</code>,
      <code>3 = Ankle</code>.
      Set <code>ADMIN_TOKEN</code> and append <code>?token=YOUR_TOKEN</code> to protect this page.
    </div>

    <div class="grid">
      <section class="label-section">
        <h2>Current Label</h2>
        <p><strong>Label:</strong> {safe_text(current_label['name'] if current_label else 'N/A')}</p>

        <div class="label-form">
          <input type="text" id="labelInput" placeholder="Enter new label" value="{safe_text(current_label['name'] if current_label else '')}" />
          <button onclick="updateLabel()">Update Label</button>
        </div>
      </section>

      <section>
        <h2>Users ({len(users)})</h2>
        <table>
          <thead>
            <tr><th>ID</th><th>Username</th><th>Created</th></tr>
          </thead>
          <tbody>
            {user_rows}
          </tbody>
        </table>
      </section>

      <section>
        <h2>ESP Devices / Nodes ({len(esps)})</h2>
        <table>
          <thead>
            <tr><th>ID</th><th>Placement</th><th>Status</th></tr>
          </thead>
          <tbody>
            {esp_rows}
          </tbody>
        </table>
      </section>

      <section>
        <h2>Labels ({len(labels)})</h2>
        <table>
          <thead>
            <tr><th>ID</th><th>Name</th></tr>
          </thead>
          <tbody>
            {label_rows}
          </tbody>
        </table>
      </section>

      <section class="label-section">
        <h2>Relabel History ({len(relabels)})</h2>
        <table>
          <thead>
            <tr>
              <th>ID</th>
              <th>Created</th>
              <th>Node</th>
              <th>Placement</th>
              <th>Original</th>
              <th>New</th>
              <th>Sensor Data</th>
            </tr>
          </thead>
          <tbody>
            {relabel_rows}
          </tbody>
        </table>
      </section>
    </div>

    {modal_html}

    <script>
      async function updateLabel() {{
        const labelInput = document.getElementById('labelInput');
        const label = labelInput.value.trim();

        if (!label) {{
          alert('Please enter a label');
          return;
        }}

        try {{
          const response = await fetch('/label', {{
            method: 'POST',
            headers: {{ 'Content-Type': 'application/json' }},
            body: JSON.stringify({{ label }})
          }});

          if (response.ok) {{
            alert('Label updated successfully');
            location.reload();
          }} else {{
            alert('Failed to update label');
          }}
        }} catch (error) {{
          alert('Error updating label: ' + error);
        }}
      }}

      function openSensorModal(id) {{
        const modal = document.getElementById(id);
        if (modal) {{
          modal.classList.add('open');
        }}
      }}

      function closeSensorModal(id) {{
        const modal = document.getElementById(id);
        if (modal) {{
          modal.classList.remove('open');
        }}
      }}

      function closeIfBackdrop(event, id) {{
        if (event.target.id === id) {{
          closeSensorModal(id);
        }}
      }}
    </script>
  </body>
</html>"""

        return html_page, 200, {"Content-Type": "text/html; charset=utf-8"}

    except Exception:
        return jsonify({"message": "Failed to load admin page"}), 500
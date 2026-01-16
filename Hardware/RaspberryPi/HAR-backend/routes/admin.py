from flask import Blueprint, request, jsonify
from database import db_all
import os

admin_bp = Blueprint('admin', __name__)

def admin_guard():
    """Simple guard using ADMIN_TOKEN for dev environments"""
    token_required = os.getenv('ADMIN_TOKEN')
    if not token_required:
        return True
    
    header_token = request.headers.get('x-admin-token')
    query_token = request.args.get('token', '')
    
    if header_token == token_required or query_token == token_required:
        return True
    
    return False

@admin_bp.route('/admin/users.json', methods=['GET'])
def get_users_json():
    if not admin_guard():
        return 'Unauthorized', 401
    
    try:
        users = db_all('SELECT id, username, created_at FROM users ORDER BY created_at DESC LIMIT 100')
        return jsonify(users)
    except Exception as err:
        return jsonify({'message': 'Failed to load users'}), 500

@admin_bp.route('/admin/esp-devices.json', methods=['GET'])
def get_esp_devices_json():
    if not admin_guard():
        return 'Unauthorized', 401
    
    try:
        esps = db_all('SELECT id, is_connected as isConnected FROM esp_devices ORDER BY id ASC LIMIT 200')
        return jsonify(esps)
    except Exception as err:
        return jsonify({'message': 'Failed to load esp devices'}), 500

@admin_bp.route('/admin', methods=['GET'])
def admin_page():
    if not admin_guard():
        return 'Unauthorized', 401
    
    try:
        users = db_all('SELECT id, username, created_at FROM users ORDER BY created_at DESC LIMIT 100')
        esps = db_all('SELECT id, is_connected as isConnected FROM esp_devices ORDER BY id ASC LIMIT 200')
        labels = db_all('SELECT id, name FROM labels')
        
        # Get current label
        current_label_query = db_all('SELECT id, name FROM labels ORDER BY id ASC LIMIT 1')
        current_label = current_label_query[0] if current_label_query else None
        
        # Generate user rows
        user_rows = ''.join([
            f'<tr><td>{u["id"]}</td><td>{u["username"]}</td><td>{u.get("created_at", "")}</td></tr>'
            for u in users
        ])
        
        # Generate ESP rows
        esp_rows = ''
        for e in esps:
            is_connected = e.get('isConnected')
            if is_connected == 1 or is_connected == True:
                status = '<span class="pill ok">connected</span>'
            elif is_connected == 0 or is_connected == False:
                status = '<span class="pill bad">disconnected</span>'
            else:
                status = '<span class="pill unk">unknown</span>'
            esp_rows += f'<tr><td>{e["id"]}</td><td>{status}</td></tr>'
        
        html = f'''<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>HAR Admin</title>
    <style>
      body {{ font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial; margin: 16px; }}
      h1 {{ margin: 0 0 8px 0; }}
      h2 {{ margin-top: 24px; }}
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
    </style>
  </head>
  <body>
    <div class="header">
      <h1>HAR Admin</h1>
      <div class="tip">Health: <span class="pill ok">ok</span></div>
    </div>
    <div class="tip">Set <code>ADMIN_TOKEN</code> env and append <code>?token=YOUR_TOKEN</code> to protect this page.</div>

    <div class="grid">
      <section class="label-section">
        <h2>Current Label</h2>
        <p><strong>Label:</strong> {current_label['name'] if current_label else 'N/A'}</p>
        <div class="label-form">
          <input type="text" id="labelInput" placeholder="Enter new label" value="{current_label['name'] if current_label else ''}" />
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
        <h2>ESP Devices ({len(esps)})</h2>
        <table>
          <thead>
            <tr><th>ID</th><th>Status</th></tr>
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
            {''.join([f'<tr><td>{l["id"]}</td><td>{l["name"]}</td></tr>' for l in labels])}
          </tbody>
        </table>
      </section>
    </div>
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
    </script>
  </body>
</html>'''
        
        return html, 200, {'Content-Type': 'text/html; charset=utf-8'}
    except Exception as err:
        return jsonify({'message': 'Failed to load admin page'}), 500

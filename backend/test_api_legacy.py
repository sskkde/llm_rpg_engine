import requests
import json

BASE_URL = "http://localhost:8000"

def test_create_save():
    response = requests.post(f"{BASE_URL}/saves")
    print(f"Create save: {response.status_code}")
    if response.status_code == 200:
        session_id = response.json()
        print(f"Session ID: {session_id}")
        return session_id
    return None

def test_list_saves():
    response = requests.get(f"{BASE_URL}/saves")
    print(f"List saves: {response.status_code}")
    if response.status_code == 200:
        saves = response.json()
        print(f"Saves: {saves}")
    return response

def test_get_snapshot(session_id):
    response = requests.get(f"{BASE_URL}/sessions/{session_id}/snapshot")
    print(f"Get snapshot: {response.status_code}")
    if response.status_code == 200:
        snapshot = response.json()
        print(f"Snapshot: {json.dumps(snapshot, indent=2, ensure_ascii=False)}")
    return response

def test_perform_turn(session_id, action):
    response = requests.post(
        f"{BASE_URL}/sessions/{session_id}/turn",
        json={"action": action}
    )
    print(f"Perform turn: {response.status_code}")
    if response.status_code == 200:
        result = response.json()
        print(f"Narrative: {result['narrative']}")
        print(f"Recommended actions: {result['recommended_actions']}")
    return response

def test_get_logs(session_id):
    response = requests.get(f"{BASE_URL}/debug/sessions/{session_id}/logs")
    print(f"Get logs: {response.status_code}")
    if response.status_code == 200:
        logs = response.json()
        print(f"Logs: {logs}")
    return response

if __name__ == "__main__":
    print("Testing LLM RPG Engine API")
    print("=" * 50)
    
    session_id = test_create_save()
    if session_id:
        test_list_saves()
        test_get_snapshot(session_id)
        test_perform_turn(session_id, "观察四周")
        test_get_logs(session_id)
    
    print("=" * 50)
    print("Test completed")
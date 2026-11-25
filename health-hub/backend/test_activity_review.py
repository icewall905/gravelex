import activity_review
import fitness
import planner
from test_dashboard_auth import client, login


def test_review_is_authenticated_and_leaves_planner_unchanged(client, monkeypatch):
    calls = []

    def review(state, prompt, context, *, synthetic):
        assert synthetic and not state["model_settings"]["web_search"]
        assert not state["workouts"] and not state["messages"]
        assert "every supplied minute" in prompt
        calls.append(context)
        return "Strong finish.", [], ["Do not save this."]

    monkeypatch.setattr(planner, "trainer_ready", lambda: True)
    monkeypatch.setattr(planner, "trainer", review)
    path = "/api/planner/activity-review"
    headers = {"X-PH-Request": "1"}
    evidence = dict(kind="run", seconds=128, active_seconds=105,
                    minutes=[{"hr": 138, "hr_seconds": 5, "distance_m": 160}, {}, {"hr": 155}])
    assert client.post(path, json=evidence, headers=headers).status_code == 401
    assert login(client).status_code == 200
    assert client.post(path, json=evidence).status_code == 403
    before = client.get("/api/planner").json
    response = client.post(path, json=evidence, headers=headers)
    assert response.status_code == 200
    assert response.json["reply"] == (
        "2 min 8 s elapsed · 1 min 45 s active · 0 min 23 s outside active time\n\nStrong finish."
    )
    assert calls[0]["minutes"] == [[1, 60, 138, 5, 160], [2, 60, None, None, None], [3, 8, 155, None, None]]
    assert client.get("/api/planner").json == before
    assert client.post(path, json={**evidence, "minutes": []}, headers=headers).status_code == 400
    assert client.post(path, json={**evidence, "manual": True}, headers=headers).status_code == 400
    assert client.post(path, json={"id": "missing"}, headers=headers).status_code == 404
    assert len(calls) == 1


def test_watch_and_synced_phone_keep_distinct_timeline_clocks(client):
    with fitness.connect() as db:
        db.execute("INSERT INTO minutes(ts,hr,steps,active,payload) VALUES(120,136,53,1,'{}')")
        db.execute("INSERT INTO minutes(ts,hr,steps,active,payload) VALUES(240,154,0,0,'{}')")
        workout = dict(start=120, seconds=125, kind="run", source="pebble")
        watch = activity_review.from_hub(db, workout)
    assert watch["clock"] == "elapsed"
    assert watch["minutes"] == [[1, 60, 136, 53, 1], [2, 60, None, None, None], [3, 5, 154, 0, 0]]
    phone = activity_review.from_hub(None, workout, {"seconds": 145, "active_seconds": 75, "heart": [[60, 155, 7]]})
    assert phone["clock"] == "active"
    assert phone["elapsed_seconds"] == 145
    assert phone["minutes"] == [[1, 60, None, None], [2, 15, 155, 7]]

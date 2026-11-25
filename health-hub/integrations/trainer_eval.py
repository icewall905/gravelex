"""Synthetic endpoint checks. Run inside health-hub web with Trainer configured."""
import json
from datetime import date, timedelta
from time import monotonic

import fitness
from zoneinfo import ZoneInfo
import planner

CASES = [
    ("start walking", "Offer two beginner walking plans, at most 20 minutes per workout.", True, 20),
    ("home strength", "I have dumbbells but no barbell. Offer two beginner home strength plans.", True, None),
    ("combined goals", "Offer two plans combining two easy runs and one strength workout.", True, None),
    ("short lunch breaks", "Offer two cycling plans. Each session must fit a 25 minute lunch break.", True, 25),
    ("no equipment", "Make a one-week bodyweight plan without gym equipment.", True, None),
    ("after a break", "I've had 3 weeks off. Give a conservative first week of exercise.", True, None),
    ("weekends only", "I can exercise only on weekends. Give a one-week walking plan.", True, None),
    ("swim and run", "Offer a plan with easy swimming and running on separate days.", True, None),
    ("recovery", "I slept badly last night. What would you consider before deciding effort today?", False, None),
    ("wearable uncertainty", "How should I interpret one low overnight HRV value?", False, None),
    ("effort", "Explain the talk test in two or three sentences.", False, None),
    ("strength progression", "How do I progress dumbbell rows when I reach the top of the rep range?", False, None),
    ("equipment swap", "What are two substitutions when a squat rack is unavailable?", False, None),
    ("low recorded volume", "How would my recent recorded workouts change a plan for me?", False, None),
    ("rest", "How do rest days fit into a beginner running plan?", False, None),
    ("explicit memory", "Remember that my apartment has stairs but no gym equipment.", False, None),
    ("reschedule", "Move this workout to a different day and keep the same duration.", True, None),
    ("calendar intent", "If I accept a suggested plan, when does it go on my calendar?", False, None),
]

today = date.today()
fitness.summary = lambda _: {
    "daily": [{"date": str(today-timedelta(days=1)), "steps":3500, "minutes":300, "resting_hr":61}],
    "workouts": [{"kind":"walking", "seconds":1200, "rpe":3}],
    "history": [{"date":str(today-timedelta(days=2)), "status":"confirmed", "load":12}],
    "recovery": {"sleep_nights":[{"date":str(today-timedelta(days=1)), "sleep_s":19800}]},
}


def run():
    results = []
    for name, message, plan, cap in CASES:
        state = {"timezone":"UTC", "workouts":[], "messages":[], "options":[],
                 "priorities":"Consistency", "activities":"Walking, running and general strength",
                 "goals":"Build sustainable fitness", "availability":"About 30 minutes most days"}
        reschedule = name == "reschedule"
        selected = None
        if reschedule:
            selected = planner.session({"title":"Easy walk", "start":str(today+timedelta(days=2))+"T17:00",
                                        "minutes":20}, ZoneInfo("UTC"))
            state["workouts"] = [selected]
        start = monotonic()
        try:
            reply, options, notes = planner.trainer(state, message, selected, reschedule=reschedule)
            assert reply.strip()
            assert not plan or options, "No proposed calendar options"
            if cap is not None:
                assert all(row["minutes"] <= cap for option in options for row in option["workouts"]), "Exceeded duration limit"
            if reschedule:
                assert all(selected["id"] in option["remove_ids"] for option in options), "Failed to replace selected workout"
                assert all(option["workouts"][0]["minutes"] == selected["minutes"] for option in options), "Did not maintain duration"
            if name == "explicit memory":
                assert any("stairs" in note.lower() for note in notes), "Did not emit a durable memory note"
            if name == "weekends only":
                assert all(date.fromisoformat(row["start"][:10]).weekday() >= 5
                           for option in options for row in option["workouts"]), "Included a weekday"
            outcome = {"case":name, "ok":True, "options":len(options)}
        except Exception as error:
            outcome = {"case":name, "ok":False, "error":type(error).__name__ + ": " + str(error)}
        outcome["seconds"] = round(monotonic()-start, 2)
        results.append(outcome)
        print(json.dumps(outcome), flush=True)
    print(json.dumps({"passed":sum(result["ok"] for result in results), "total":len(results)}), flush=True)
    return all(row["ok"] for row in results)


if __name__ == "__main__":
    raise SystemExit(0 if run() else 1)

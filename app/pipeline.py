from app.agent.conversation import gate_request
from app.agent.parser import parse_request
from app.allocator import allocate


def process_request(text: str, objective: str = "min_lateness"):
    request = parse_request(text)
    terminal, order = gate_request(request)
    result = terminal or allocate(request, order, objective)
    return {"request": request.to_dict(), "result": result.to_dict()}


# Multi-Agent System - Quick Start Guide

## Overview

The portfolio assistant now uses a 6-agent orchestration system that validates, routes, specializes, and synthesizes answers to questions about Kate.

## Endpoint

**URL**: `POST /run-multi-agent`

## Request Format

```json
{
  "session_id": "user_session_id",
  "message": "Your question about Kate's experience"
}
```

## Response Format

```json
{
  "status": "success",
  "answer": "Full synthesized answer from agents",
  "question_id": 42,
  "agent_runs_count": 6
}
```

## Example Requests

### Question 1: Technical Skills
```bash
curl -X POST http://localhost:8000/run-multi-agent \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "session_1",
    "message": "What programming languages does Kate know?"
  }'
```

**Expected Agent Flow**:
1. ✓ Validation Agent: ON_TOPIC
2. ✓ Routing Agent: ["skills_agent"]
3. ✓ Skills Agent: Retrieves Kate's skills
4. ✓ Answer Agent: Synthesizes response
5. ✓ All runs logged to database

### Question 2: Project Experience
```bash
curl -X POST http://localhost:8000/run-multi-agent \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "session_2",
    "message": "Tell me about Lamabot project"
  }'
```

**Expected Agent Flow**:
1. ✓ Validation Agent: ON_TOPIC
2. ✓ Routing Agent: ["project_agent"]
3. ✓ Project Agent: Gets project details
4. ✓ Answer Agent: Formats answer
5. ✓ All runs logged

### Question 3: Off-Topic
```bash
curl -X POST http://localhost:8000/run-multi-agent \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "session_3",
    "message": "What is the weather today?"
  }'
```

**Expected Response**:
- Validation Agent rejects as OFF_TOPIC
- Returns polite redirect message
- Still logged to database

## Database Schema

### Questions Table
```sql
SELECT * FROM questions 
WHERE session_id = 'session_1'
ORDER BY created_at DESC;
```

### Agent Runs Table
```sql
SELECT 
  agent_name,
  status,
  (end_time - start_time) as duration_ms,
  output
FROM agent_runs 
WHERE question_id = 42
ORDER BY id;
```

## Performance Expectations

| Agent | Typical Time |
|-------|--------------|
| Validation | ~500ms |
| Routing | ~300ms |
| Resume/Skills/Project | ~1000ms each |
| Answer | ~800ms |
| **Total** | **~4-5s** |

## Architecture

```
User Question
    ↓
Validation Agent (reject or continue)
    ↓
Routing Agent (select which agents needed)
    ↓
Specialized Agents (resume/skills/project)
    ↓
Answer Agent (synthesize)
    ↓
Log All Runs + Return Answer
```

## How It Works

1. **Question comes in**: POST to `/run-multi-agent`
2. **Session created**: If new session_id, creates session record
3. **Question logged**: Creates question record in database
4. **Validation**: Checks if question is about Kate's profile
5. **Routing**: AI determines which specialized agents to call
6. **Specialization**: 
   - Resume Agent (if career/education question)
   - Skills Agent (if technical question)
   - Project Agent (if project question)
7. **Synthesis**: Answer Agent combines results into coherent response
8. **Logging**: All 6 agent runs saved to `agent_runs` table
9. **Response**: Answer returned to client

## Debugging

### View Agent Execution
```sql
SELECT 
  agent_name,
  status,
  output,
  start_time,
  end_time
FROM agent_runs 
WHERE question_id = ?
ORDER BY start_time;
```

### Check Why Answer Was Rejected
```sql
SELECT output 
FROM agent_runs 
WHERE question_id = ? AND agent_name = 'validation_agent';
```

### Trace Routing Decision
```sql
SELECT output 
FROM agent_runs 
WHERE question_id = ? AND agent_name = 'routing_agent';
```

## Common Errors

### "Missing session_id or message"
**Cause**: Request JSON missing required fields
**Fix**: Ensure both `session_id` and `message` are provided

### Agent returns error status
**Cause**: Tool or model failure
**Check**: View `agent_runs` table output for details
**Fallback**: System handles gracefully and continues

### Empty answer
**Cause**: Routing to wrong agents or tool not finding data
**Fix**: Verify knowledge base files exist and tools work

## Integration with Frontend

Update `app.js` to use new endpoint:

```javascript
const response = await fetch('http://localhost:8000/run-multi-agent', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    session_id: currentSessionId,
    message: userMessage
  })
});

const data = await response.json();
if (data.status === 'success') {
  displayMessage(data.answer);
  console.log(`${data.agent_runs_count} agents involved`);
}
```

## Monitoring

Track agent performance:
```sql
SELECT 
  agent_name,
  COUNT(*) as run_count,
  AVG(CAST((julianday(end_time) - julianday(start_time)) * 86400000 AS FLOAT)) as avg_time_ms,
  SUM(CASE WHEN status='error' THEN 1 ELSE 0 END) as error_count
FROM agent_runs
GROUP BY agent_name;
```

## Migration from Old Single-Agent

Old endpoint `/run` (ADK default) still works but is single-agent.
New endpoint `/run-multi-agent` uses the 6-agent system.

Frontend can use either, but `/run-multi-agent` provides:
- ✓ Specialized agent routing
- ✓ Better accuracy
- ✓ Full execution visibility
- ✓ Agent run logging

## References

- [Architecture Details](MULTI_AGENT_ARCHITECTURE.md)
- [Orchestration Code](../backend/app/orchestration.py)
- [Agent Definitions](../backend/app/multi_agent.py)

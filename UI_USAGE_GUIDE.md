# UI/UX Usage Guide

Professional Streamlit UI for Autonomous Network Troubleshooting.

---

## 🚀 Quick Start

### 1. Import the UI Module

```python
# In your app.py
from streamlit_autonomous_ui import main as render_autonomous_ui

# In your workspace selection:
elif workspace == "Autonomous Troubleshooting":
    render_autonomous_ui()
```

### 2. Run

```bash
streamlit run app.py
```

---

## 🎨 UI Features

### **Professional Design**
- ✨ Modern gradient styling with custom CSS
- 📱 Fully responsive layout
- 🎯 Clear visual hierarchy
- ⚡ Smooth animations and transitions

### **Step-by-Step Workflow**
1. **Mode Selection** - Choose your path (A/B/C)
2. **Problem Description** - Describe the issue
3. **Auto-Diagnosis** - System analyzes the problem
4. **Fix Review** (Path B) - Approve before execution
5. **Execution** - Safe fix application
6. **Results** - Clear success/failure indication
7. **Feedback** - Help the system learn

### **Visual Elements**
| Element | Purpose |
|---------|---------|
| Mode Cards | Easy selection with descriptions |
| Problem Input | Large text area with examples |
| Metrics Grid | Real-time problem classification |
| Progress Indicators | Step-by-step workflow visibility |
| Result Cards | Clear success/error/warning states |
| Status Badges | Quick status identification |
| Timeline | Execution trace visualization |

---

## 📊 Dashboard Features

### **System Statistics**
- 📚 Total Patterns Learned
- ✅ Success Rate
- 🖥️ Managed Devices
- 🔮 Auto-Fix Readiness

### **Learning Progress**
- Shows pattern collection progress
- Indicates readiness for Path A
- Tracks learning milestones

---

## 🎯 User Flows

### **Path B: On-Demand (Week 1)**
```
1. User selects "👨‍💼 Path B: On-Demand"
   ↓
2. Describes problem: "Network slow between NYC and SF"
   ↓
3. System auto-diagnoses in 2-5 minutes
   ↓
4. Shows fix with explanation & commands
   ↓
5. User clicks "✅ Approve & Apply"
   ↓
6. System executes with pre/post checks
   ↓
7. Shows clear success/failure result
   ↓
8. Collects feedback for learning
```

### **Path C: Learning (Week 1-2)**
```
1. User selects "📚 Path C: Learning"
   ↓
2. Describes problem
   ↓
3. System auto-diagnoses
   ↓
4. Shows: "We've seen this 3 times before (75% success rate)"
   ↓
5. System stores pattern for future
   ↓
6. User provides feedback
   ↓
7. Pattern confidence increases
```

### **Path A: Autonomous (Week 4+)**
```
1. User selects "🤖 Path A: Autonomous"
   ↓
2. Describes problem
   ↓
3. System predicts issues + diagnoses
   ↓
4. If high confidence + good track record:
      → Auto-applies fix automatically ⚡
   Else:
      → Queues for approval
   ↓
5. Shows result
   ↓
6. Collects feedback
```

---

## 🎨 Color Scheme

| Color | Usage |
|-------|-------|
| `#667eea` | Primary (buttons, headers) |
| `#764ba2` | Accent (gradients) |
| `#28a745` | Success |
| `#dc3545` | Error |
| `#ffc107` | Warning |
| `#0c5460` | Info |

---

## 📱 Responsive Breakpoints

- **Desktop** (1200px+): Full layout with 3-column cards
- **Tablet** (768px-1199px): 2-column layout
- **Mobile** (<768px): Single column, stacked layout

---

## ⌨️ Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Enter` in textarea | New line (Shift+Enter to submit) |
| `Tab` | Navigate between elements |
| `Space` | Toggle checkboxes |

---

## 🔍 Examples

### Example 1: Network Slowness (Path B)

```
Mode: 👨‍💼 Path B: On-Demand

Problem:
"Users in the San Francisco office report network slowness 
when accessing databases in AWS"

System Output:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Scope:        path
Symptom:      performance
Severity:     high
Confidence:   89%
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Root Cause:
🎯 MTU mismatch on WAN link between SF and AWS

Proposed Fix:
🔧 Set interface MTU to 1500

Commands:
interface GigabitEthernet0/0
 mtu 1500

Rollback Plan:
interface GigabitEthernet0/0
 mtu 1514

[✅ Approve & Apply] [❌ Reject]

✅ Fix Applied Successfully
   Status: Complete
   Outcome: Fixed
   Duration: 42 seconds

💬 Feedback:
"Yes, network is back to normal speed"
[📤 Submit Feedback]
```

### Example 2: BGP Instability (Path C)

```
Mode: 📚 Path C: Learning

Problem:
"BGP neighbors keep flapping on core router"

System Output:
✨ Similar issue found: success rate 75% in 4 past incidents
  Suggested: "Clear BGP session and check MTU"

Root Cause:
🎯 BGP session instability due to configuration mismatch

Pattern Stored ✓
📚 Pattern ID: abc123def456

💬 Feedback:
"No, still flapping"
[📤 Submit Feedback]

Pattern Updated:
Success rate adjusted from 75% to 60%
```

---

## 🛠️ Customization

### Change Theme Colors

Edit `CUSTOM_CSS` in `streamlit_autonomous_ui.py`:

```python
CUSTOM_CSS = """
<style>
    /* Change primary gradient */
    .primary-button {
        background: linear-gradient(135deg, #YOUR_COLOR_1 0%, #YOUR_COLOR_2 100%);
    }
</style>
"""
```

### Change Text/Labels

Edit the render functions, e.g.:

```python
def render_mode_selection():
    st.markdown("### Your Custom Title Here")
    # ...
```

### Add Custom Metrics

Edit `render_statistics()`:

```python
def render_statistics(troubleshooter):
    # ... existing code ...
    
    # Add your metric:
    with col_new:
        st.metric(
            "🆕 Your Metric",
            your_value,
            help="Explanation"
        )
```

---

## 📱 Mobile Optimization

The UI is fully responsive:

```
Desktop (1200px+):      3 columns
Tablet (768-1199px):    2 columns
Mobile (<768px):        1 column (stacked)
```

No additional configuration needed!

---

## 🚨 Error Handling

### User Error: No Mode Selected
```
ℹ️ 👈 Select a troubleshooting mode above
```

### User Error: No Problem Entered
```
ℹ️ 👈 Describe a problem to get started
```

### System Error: Diagnosis Failed
```
❌ Could not diagnose this problem
Please try with a more specific description
```

### System Error: Fix Failed
```
❌ Execution Error
Status: execution_failed
Errors: 1 error(s)
- SSH to router-A failed: Connection timeout
```

---

## 🔐 Security

### Command Validation
All commands are validated before execution:
- ✅ `interface Gi0/0` - Safe
- ❌ `reload` - Dangerous (blocked)
- ❌ `write erase` - Dangerous (blocked)

### Pre-Check Safety
```
✅ Device reachable
✅ All commands safe
✅ Syntax valid
✅ No dangerous patterns found
→ Ready to execute
```

### Post-Check Verification
```
✅ Fix verification passed
✅ Expected outcome found in output
✅ No errors detected
→ Fix confirmed successful
```

---

## 📊 Learning Progress Milestones

| Week | Status | Path A Ready? |
|------|--------|---------------|
| Week 1 | 0-5 patterns | ❌ No |
| Week 2 | 5-15 patterns | ❌ No |
| Week 3 | 15-25 patterns | ⚠️ Almost |
| Week 4+ | 25+ patterns, >80% success | ✅ Yes |

---

## 💡 Tips for Best Results

### **Path B (On-Demand)**
- Be specific in problem description
- Include affected regions/devices
- Mention any recent changes
- Provide time of issue onset

### **Path C (Learning)**
- Provide detailed feedback
- Include actual outcome (fixed/degraded/no change)
- Add notes on any workarounds
- This builds the pattern database

### **Path A (Autonomous)**
- Only activates after learning phase
- Automatic for known issues (>80% success)
- Still requires approval for unknown issues
- Keeps you in control while automating routine fixes

---

## 🎯 Success Metrics

Track these to measure success:

| Metric | Target | Timeline |
|--------|--------|----------|
| MTTR (Mean Time to Repair) | <5 min | Week 1 |
| Pattern Collection Rate | 5-10/week | Week 1-2 |
| Success Rate | >75% | Week 2-3 |
| Auto-Fix Rate | >50% | Week 4+ |
| User Satisfaction | >4/5 | Ongoing |

---

## 🔧 Troubleshooting the UI

### UI doesn't load
```bash
# Clear Streamlit cache
streamlit cache clear

# Restart server
streamlit run app.py --logger.level=debug
```

### CSS not applying
- Check browser cache (Ctrl+F5)
- Ensure `CUSTOM_CSS` is before other content

### Buttons not responsive
- Verify `use_container_width=True` is set
- Check for overlapping elements

---

## 📞 Support

For UI issues:
1. Check the `🛠️ Troubleshooting the UI` section above
2. Review `AUTONOMOUS_SETUP_GUIDE.md`
3. Check browser console (F12 → Console tab)
4. Look for error messages in Streamlit terminal

---

**Ready to troubleshoot?** Run `streamlit run app.py` and select your mode! 🚀

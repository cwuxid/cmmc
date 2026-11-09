# Auditorium exit modeling — conversation transcript

## User

I want to model a group of people exiting an auditorium. Here is my idea for how to do it. Firstly, treat each person as a unit y_i index by their seat. To make a decision about how to exit, each person is assigned an individual utility function that is used to make decisions between different exiting paths. First, assume that each unit does not know the shortest path to exit between their seat and the exit. The only decision they make is between their seat, the next exit egress, the next egress, and so forth and so on. Next, assume each unit also has their own vector of weights that represent behavioral biases. They  make those choices individually, but clearly affect each other in the process. Some of them might be brutally rational (what’s the quickest way out?), others may be influenced by habit (how did I enter this room?), peer pressure (which way is everyone going?), or social norms (it would be rude to rush ahead of others!).  What appears to be the best strategy for each individual might end up impeding the motion of the whole group, but nonetheless each unit optimizes their decision based on the utility function subject to the weights. How would we structure this kind of problem to simulate the exit? Lets try to build this from first principles on a unit level analysis rather than implementing the building constraints first

## Assistant — progress update

I’ll start with the individual’s information, preferences, and movement rules, then show how their interactions produce queues and collective exit patterns. I’ll also check the relevant modeling literature to ground the structure.

## Assistant

I would structure this as an **agent-based model of sequential decisions under partial information**. Each person chooses a next action using their own preferences and beliefs; the crowd’s behavior emerges because those actions change what everyone else sees and can do.

The key distinction is between **what a person wants to do, what they believe will happen, and what movement is physically possible**. A utility function describes the first two, but we also need an interaction rule to turn decisions into movement.

Here is a formulation built from the individual outward.

**1. Define the person’s state separately from their preferences.**

Let \(i\) identify a person by their initial seat. Their location changes, but their identity remains fixed.

Write their state at time \(t\) as

\[
s_i(t)=\bigl(x_i(t),g_i(t),m_i(t),b_i(t),z_i(t)\bigr),
\]

where:

- \(x_i(t)\): current position.
- \(g_i(t)\): current intermediate target, such as a row opening or aisle junction.
- \(m_i(t)\): memory, including their entrance route and recent decisions.
- \(b_i(t)\): beliefs about available directions, congestion, and likely delays.
- \(z_i(t)\): movement status, such as seated, walking, waiting, or exited.

Separately, assign a preference vector

\[
\theta_i=(w_{T,i},w_{H,i},w_{P,i},w_{N,i},w_{S,i}).
\]

These weights represent sensitivity to time, habit, peer behavior, social norms, and switching direction. Start with fixed weights; changing preferences under stress can come later.

**2. Give each person an information boundary.**

The simulation may know the whole auditorium. The individual should only receive an observation:

\[
o_i(t)=O_i\bigl(S(t)\bigr),
\]

where \(S(t)\) is the full population state.

An observation might contain nearby people, visible openings, observed movement, and remembered entrance information. It should not silently include the true shortest route or congestion around an unseen corner.

This makes an important distinction: **a person can be rational about saving time while having incomplete or incorrect information**. Rationality does not require knowing the building.

Also, following others can reflect either a preference for conformity or a belief that others know the way. Those are different mechanisms. I would initially model them separately.

**3. Define actions as local commitments.**

At a decision point, the person chooses from a perceived action set:

\[
\mathcal A_i(t)
=
\{\text{move toward opening A},\text{move toward opening B},
\text{wait},\text{yield}\}.
\]

Later, at a junction, a new set becomes available.

Your sequence is therefore:

\[
\text{seat}\rightarrow\text{row opening}
\rightarrow\text{aisle junction}\rightarrow\text{door}.
\]

The person chooses the next target, without selecting a complete route in advance. Include waiting and yielding explicitly; otherwise the model cannot express some of the social behavior you describe.

**4. Score actions using perceived consequences.**

A useful starting utility is

\[
\begin{aligned}
U_i(a,t)=
&-w_{T,i}\widehat{\tau}_i(a,t)
+w_{H,i}H_i(a,t)\\
&+w_{P,i}P_i(a,t)
-w_{N,i}N_i(a,t)
-w_{S,i}C_i(a,t).
\end{aligned}
\]

The terms mean:

| Term | Interpretation |
|---|---|
| \(\widehat{\tau}_i(a,t)\) | Perceived time to reach the next target, including expected waiting |
| \(H_i(a,t)\) | Familiarity with the action, especially from entering |
| \(P_i(a,t)\) | Observed support for that direction among nearby people |
| \(N_i(a,t)\) | Perceived norm violation, such as cutting ahead |
| \(C_i(a,t)\) | Cost of abandoning the current direction or target |

For a strictly local first version, \(\widehat{\tau}\) covers only the next target. That is a **myopic** decision rule. Later, you could add a subjective estimate of what lies beyond that target without granting global route knowledge.

For example,

\[
\widehat{\tau}_i(a,t)
=
\frac{\widehat d_i(a,t)}{v_i}
+\widehat q_i(a,t),
\]

where \(\widehat q_i\) is perceived waiting time.

Someone may therefore see many people choosing left, which increases its social appeal, while also seeing a long queue, which increases its perceived cost. Those effects can coexist. Experimental research likewise suggests that following or avoiding a crowd depends on the information available to the person. [Haghani and Sarvi, 2017](https://www.sciencedirect.com/science/article/pii/S0003347216303190)

Use consistent feature scales so that the weights have interpretable meanings.

**5. Specify how utility becomes a choice.**

For deterministic optimization,

\[
a_i^*(t)=\arg\max_{a\in\mathcal A_i(t)}U_i(a,t).
\]

Alternatively, allow imperfect consistency:

\[
\Pr(a_i(t)=a)
=
\frac{\exp\!\left(U_i(a,t)/\lambda_i\right)}
{\sum_{a'\in\mathcal A_i(t)}
\exp\!\left(U_i(a',t)/\lambda_i\right)}.
\]

Here, small \(\lambda_i\) means choices closely follow the highest utility; larger values produce more variability.

Keep this separate from behavioral weights: strong habit can be a consistent preference, rather than decision noise.

Also specify *when* people reconsider: on reaching a junction, after being blocked for a while, or at occasional decision intervals. Otherwise small fluctuations can cause implausible repeated reversals.

**6. Make interactions determine actual movement.**

Suppose two people both choose to enter the same opening. Their utilities cannot both determine who moves first.

You need a minimal movement rule:

- People occupy space and cannot overlap.
- Walking takes time.
- A contested space admits only the permitted number of people.
- Unsuccessful movement attempts produce waiting.

You can start with abstract positions and links, without auditorium dimensions. But **some spatial exclusion or limited throughput is necessary for congestion to exist**.

For contested moves, use an explicit rule—for example, earliest arrival, with random resolution of simultaneous ties. Yielding can withdraw a person’s claim before that resolution. Avoid making the person with the highest private utility automatically win.

Conflict resolution matters: pedestrian models show that friction between competing movements can materially change evacuation outcomes. [Kirchner, Nishinari, and Schadschneider, 2003](https://arxiv.org/abs/cond-mat/0209383)

**7. Close the feedback loop.**

Each simulation step becomes:

1. Everyone observes the current state.
2. They update their beliefs.
3. Those due to reconsider choose an action.
4. Movement requests are resolved together.
5. Positions, waiting times, and memories update.
6. The process repeats until everyone exits.

Using a common observation snapshot avoids giving people an advantage merely because their record appears earlier in the simulation’s processing order.

The essential feedback is

\[
\text{individual choices}
\rightarrow
\text{movement and queues}
\rightarrow
\text{new observations}
\rightarrow
\text{revised choices}.
\]

That feedback makes other people’s behavior endogenous.

For the first experiment, I would use **one group, two local alternatives, and one shared downstream merge**. Hold that small environment fixed and vary the distribution of behavioral weights. Measure individual exit times, total clearance time, waiting, and route switching over repeated runs.

This lets you ask whether time-focused choices create more conflict, whether habit concentrates demand, and whether yielding improves throughput. None of those outcomes should be assumed: **collective inefficiency is a hypothesis for the simulation to test**, even when every person chooses their highest perceived utility.

## User

Can you save the transcript into the working directory

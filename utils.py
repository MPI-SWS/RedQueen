# Helper functions

import matplotlib
from matplotlib import pyplot as py
import multiprocessing as mp
import numpy as np
import pandas as pd
import sys
import datetime as D

## Utilities

def mb(val, default):
    return val if val is not None else default


def logTime(chkpoint):
    print('*** \x1b[31m{}\x1b[0m Checkpoint: {}'.format(D.datetime.now(), chkpoint))
    sys.stdout.flush()


def def_q_vec(num_followers):
    """Returns the default q_vec for the given number of followers."""
    return np.ones(num_followers, dtype=float) / (num_followers ** 2)


def is_sorted(x, ascending=True):
    """Determines if a given numpy.array-like is sorted in ascending order."""
    return np.all((np.diff(x) * (1.0 if ascending else -1.0) >= 0))


## Metrics

def rank_of_src_in_df(df, src_id, fill=True, with_time=True):
    """Calculates the rank of the src_id at each time instant in the list of events."""

    assert is_sorted(df.t.values), "Array not sorted by time."

    def steps_to(x):
        return (np.arange(1, len(x) + 1) -
                np.maximum.accumulate(
                    np.where(x == src_id, range(1, len(x) + 1), 0)))

    df2 = df.copy()
    df2['rank'] = (df.groupby('sink_id')
                     .src_id
                     .transform(steps_to)
                     .astype(float))

    pivot_ranks = df2.pivot_table(index='t' if with_time else 'event_id',
                                  columns='sink_id', values='rank')
    return pivot_ranks.fillna(method='ffill') if fill else pivot_ranks


def u_int_opt(df, src_id=None, end_time=None, q_vec=None, s=None,
              follower_ids=None, sim_opts=None):
    """Calculate the ∫u(t)dt for the given src_id assuming that the broadcaster
    was following the optimal strategy."""

    if sim_opts is not None:
        src_id       = mb(src_id, sim_opts.src_id)
        end_time     = mb(end_time, sim_opts.end_time)
        q_vec        = mb(q_vec, sim_opts.q_vec)
        s            = mb(s, sim_opts.s)
        follower_ids = mb(follower_ids, sim_opts.sink_ids)

    if follower_ids is None:
        follower_ids = sorted(df.sink_id[df.src_id == src_id].unique())
    else:
        assert is_sorted(follower_ids)

    r_t      = rank_of_src_in_df(df, src_id)
    u_values = r_t[follower_ids].values.dot(np.sqrt(q_vec / s))
    u_dt     = np.diff(np.concatenate([r_t.index.values, [end_time]]))

    return np.sum(u_values * u_dt)


def time_in_top_k(df, K, src_id=None, end_time=None, sim_opts=None):
    """Calculate ∫I(r(t) <= k)dt for the given src_id."""

    # if follower_ids is None:
    #     follower_ids = sorted(df[df.src_id == src_id].sink_id.unique())

    if sim_opts is not None:
        src_id       = mb(src_id, sim_opts.src_id)
        end_time     = mb(end_time, sim_opts.end_time)

    r_t      = rank_of_src_in_df(df, src_id)
    I_values = np.where(r_t.mean(1) <= K - 1, 1.0, 0.0)
    I_dt     = np.diff(np.concatenate([r_t.index.values, [end_time]]))

    return np.sum(I_values * I_dt)


def average_rank(df, src_id=None, end_time=None, sim_opts=None, **kwargs):
    """Calculate ∫r(t)dt for the given src_id."""

    # if follower_ids is None:
    #     follower_ids = sorted(df[df.src_id == src_id].sink_id.unique())

    if sim_opts is not None:
        src_id       = mb(src_id, sim_opts.src_id)
        end_time     = mb(end_time, sim_opts.end_time)

    r_t  = rank_of_src_in_df(df, src_id)
    r_dt = np.diff(np.concatenate([r_t.index.values, [end_time]]))

    return np.sum(r_t.mean(1) * r_dt)


def calc_loss_poisson(df, u_const, src_id=None, end_time=None,
                      q_vec=None, s=None, follower_ids=None, sim_opts=None):
    """Calculate the loss for the given source assuming that it was Poisson
    with rate u_const."""

    if sim_opts is not None:
        src_id       = mb(src_id, sim_opts.src_id)
        end_time     = mb(end_time, sim_opts.end_time)
        q_vec        = mb(q_vec, sim_opts.q_vec)
        s            = mb(s, sim_opts.s)
        follower_ids = mb(follower_ids, sim_opts.sink_ids)

    assert is_sorted(follower_ids)

    if q_vec is None:
        q_vec = def_q_vec(len(follower_ids))

    r_t = rank_of_src_in_df(df, src_id)
    q_t = 0.5 * np.square(r_t[follower_ids].values).dot(q_vec)
    s_t = 0.5 * s * np.ones(r_t.shape[0], dtype=float) * (u_const ** 2)

    return pd.Series(data=q_t + s_t, index=r_t.index)


def calc_loss_opt(df, sim_opts):
    """Calculate the loss for the given source assuming that it was the
    optimal broadcaster."""

    follower_ids = sim_opts.sink_ids
    q_vec        = sim_opts.q_vec
    src_id       = sim_opts.src_id

    r_t = rank_of_src_in_df(df, src_id)
    q_t = 0.5 * np.square(r_t[follower_ids].values).dot(q_vec)
    s_t = q_t # For the optimal solution, the q_t is the same is s_t

    return pd.Series(data=q_t + s_t, index=r_t.index)


## Oracle

def oracle_ranking(df, sim_opts, omit_src_ids=None, follower_ids=None):
    """Returns the best places the oracle would have put events. Optionally, it
    can remove sources, use a custom weight vector and have a custom list of
    followers."""

    if omit_src_ids is not None:
        df = df[~df.src_id.isin(omit_src_ids)]

    if follower_ids is not None:
        df = sorted(df[df.sink_id.isin(follower_ids)])
    else:
        follower_ids = sorted(df.sink_id.unique())

    assert len(follower_ids) == 1, "Oracle has been implemented only for 1 follower."

    # TODO: Will need to update q_vec manually if we want to run the method
    # for a subset of the user's followers.
    q_vec = sim_opts.q_vec
    s = sim_opts.s

    assert is_sorted(df.t.values), "Dataframe is not sorted by time."
    event_times = df.groupby('event_id').t.mean()

    n = event_times.shape[0]
    if n > 1e6:
        print('Not running for n > 1e6 events')
        return []

    w = np.diff(np.concatenate([[0.0], [0.0], event_times.values, [sim_opts.end_time]]))

    # TODO: Check index/off by one.
    # Initialization sets the final penalty.
    J = np.zeros((n + 1, n + 2), dtype=float)

    J[:, n + 1] = (np.arange(n + 1) ** 2) / 2

    for k in range(n, -1, -1):
        # This can be made parallel and vectorized
        # Also, not the whole matrix needs to be filled in (reduce run-time by 50%)
        for r in range(min(k + 1, n)):
            J[r, k] = min(0.5 * s + J[0, k + 1],
                          0.5 * q_vec * w[k + 1] * ((r + 1) ** 2) + J[r + 1, k + 1])

    # We are implicitly assuming that the oracle starts with rank 0
    oracle_ranks = np.zeros(n + 1, dtype=int)
    u_star = np.zeros(n + 1, dtype=int)
    for k in range(n):
        lhs = 0.5 * s + J[0, k + 1]
        rhs = 0.5 * q_vec * w[k + 1] * ((oracle_ranks[k] + 1) ** 2) + J[oracle_ranks[k] + 1, k + 1]
        if lhs < rhs:
            u_star[k] = 1
            oracle_ranks[k + 1] = 0
        else:
            u_star[k] = 0
            oracle_ranks[k + 1] = oracle_ranks[k] + 1

    oracle_df = pd.DataFrame.from_dict({
        'ranks'   : oracle_ranks,
        'events'  : u_star,
        'at'      : np.concatenate([[0.0], event_times.values]),
        't'       : np.concatenate([[0.0], event_times.values]),
        't_delta' : w[1:]
    })

    return oracle_df, J[0, 0]


def get_oracle_df(sim_opts, with_cost=False):
    wall_mgr = sim_opts.create_manager_for_wall()
    wall_mgr.run()
    oracle_df, cost = oracle_ranking(df=wall_mgr.state.get_dataframe(),
                                     sim_opts=sim_opts)

    if with_cost:
        return oracle_df, cost
    else:
        return oracle_df


def find_opt_oracle(target_events, sim_opts, tol=1e-2, verbose=False):
    """Sweep the 's' parameter and get the best run of the oracle."""
    s_hi, s_init, s_lo = 1.0 * 2, 1.0, 1.0 / 2

    def oracle_num_events(s):
        oracle_df = get_oracle_df(sim_opts.update({ 's': s }))
        return oracle_df.events.sum()

    num_events = oracle_num_events(s_init)

    if num_events > target_events:
        while True:
            s_lo = s_init
            s_init *= 2
            s_hi = s_init
            num_events = oracle_num_events(s_init)
            if verbose:
                logTime('s_lo = {}, s_hi = {}, num_events = {} '
                        .format(s_lo, s_hi, num_events))
            if num_events < target_events:
                break
    elif num_events < target_events:
        while True:
            s_hi = s_init
            s_init /= 2
            s_lo = s_init
            num_events = oracle_num_events(s_init)
            if verbose:
                logTime('s_lo = {}, s_hi = {}, num_events = {} '
                        .format(s_lo, s_hi, num_events))
            if num_events > target_events:
                break

    if verbose:
        logTime('s_lo = {}, s_hi = {}'.format(s_lo, s_hi))

    while True:
        s_try = (s_lo + s_hi) / 2.0
        oracle_df, cost = get_oracle_df(sim_opts.update({ 's': s_try }),
                                        with_cost=True)
        opt_events = oracle_df.events.sum()

        if verbose:
            logTime('s_try = {}, events = {}, cost = {}'.format(s_try, opt_events, cost))

        if np.abs(opt_events - target_events) / (target_events * 1.0) < tol or \
            (opt_events == np.ceil(target_events)) or \
            (opt_events == np.floor(target_events)):
            return {
                's': s_try,
                'cost': cost,
                'df': oracle_df
            }
        elif opt_events < target_events:
            s_hi = s_try
        else:
            s_lo = s_try


def find_opt_oracle_s(target_events, sim_opts, tol=1e-1, verbose=False):
    res = find_opt_oracle(target_events, sim_opts, tol, verbose)
    return res['s']


def find_opt_oracle_time_top_k(target_events, K, sim_opts, tol=1e-1, verbose=False):
    res = find_opt_oracle(target_events, sim_opts, tol, verbose)
    df = res['df']
    return np.sum(df.t_delta[df.ranks <= K - 1])


## LaTeX

SPINE_COLOR = 'grey'
def latexify(fig_width=None, fig_height=None, columns=1, largeFonts=False):
    """Set up matplotlib's RC params for LaTeX plotting.
    Call this before plotting a figure.

    Parameters
    ----------
    fig_width : float, optional, inches
    fig_height : float,  optional, inches
    columns : {1, 2}
    """

    # code adapted from http://www.scipy.org/Cookbook/Matplotlib/LaTeX_Examples

    # Width and max height in inches for IEEE journals taken from
    # computer.org/cms/Computer.org/Journal%20templates/transactions_art_guide.pdf

    assert(columns in [1,2])

    if fig_width is None:
        fig_width = 3.39 if columns == 1 else 6.9 # width in inches

    if fig_height is None:
        golden_mean = (np.sqrt(5)-1.0)/2.0    # Aesthetic ratio
        fig_height = fig_width*golden_mean # height in inches

    MAX_HEIGHT_INCHES = 8.0
    if fig_height > MAX_HEIGHT_INCHES:
        print("WARNING: fig_height too large:" + fig_height +
              "so will reduce to" + MAX_HEIGHT_INCHES + "inches.")
        fig_height = MAX_HEIGHT_INCHES

    params = {'backend': 'ps',
              'text.latex.preamble': ['\\usepackage{gensymb}'],
              'axes.labelsize': 10 if largeFonts else 7, # fontsize for x and y labels (was 10)
              'axes.titlesize': 10 if largeFonts else 7,
              'font.size': 10 if largeFonts else 7, # was 10
              'legend.fontsize': 10 if largeFonts else 7, # was 10
              'xtick.labelsize': 10 if largeFonts else 7,
              'ytick.labelsize': 10 if largeFonts else 7,
              'text.usetex': True,
              'figure.figsize': [fig_width,fig_height],
              'font.family': 'serif',
              'xtick.minor.size': 0.5,
              'xtick.major.pad': 1.5,
              'xtick.major.size': 1,
              'ytick.minor.size': 0.5,
              'ytick.major.pad': 1.5,
              'ytick.major.size': 1
    }

    matplotlib.rcParams.update(params)
    py.rcParams.update(params)


def format_axes(ax):

    for spine in ['top', 'right']:
        ax.spines[spine].set_visible(False)

    for spine in ['left', 'bottom']:
        ax.spines[spine].set_color(SPINE_COLOR)
        ax.spines[spine].set_linewidth(0.5)

    ax.xaxis.set_ticks_position('bottom')
    ax.yaxis.set_ticks_position('left')

    for axis in [ax.xaxis, ax.yaxis]:
        axis.set_tick_params(direction='out', color=SPINE_COLOR)

    return ax


## Sweeping s

def q_int_worker(params):
    sim_opts, seed = params
    m = sim_opts.create_manager_with_opt(seed)
    m.run()
    return u_int_opt(m.state.get_dataframe(), sim_opts=sim_opts)


def calc_q_capacity_iter(sim_opts_gen, s, seeds=None, parallel=True):
    if seeds is None:
        seeds = range(10)

    def _get_sim_opts():
        return sim_opts_gen().update({ 's': s })

    capacities = np.zeros(len(seeds), dtype=float)
    if not parallel:
        for idx, seed in enumerate(seeds):
            m = _get_sim_opts().create_manager(seed)
            m.run()
            capacities[idx] = u_int_opt(m.state.get_dataframe(),
                                        sim_opts=_get_sim_opts())
    else:
        num_workers = min(len(seeds), mp.cpu_count())
        with mp.Pool(num_workers) as pool:
            for (idx, capacity) in \
                enumerate(pool.imap(q_int_worker, [(_get_sim_opts(), x)
                                                   for x in seeds])):
                capacities[idx] = capacity

    return capacities


def sweep_s(sim_opts_gen, capacity_cap, tol=1e-2, verbose=False, s_init=1.0):
    # We know that on average, the ∫u(t)dt decreases with increasing 's'

    # Step 1: Find the upper/lower bound by exponential increase/decrease
    init_cap = calc_q_capacity_iter(sim_opts_gen, s_init).mean()

    if verbose:
        logTime('Initial capacity = {}'.format(init_cap))

    s = s_init
    if init_cap < capacity_cap:
        while True:
            s_hi = s
            s /= 2.0
            s_lo = s
            if calc_q_capacity_iter(sim_opts_gen, s).mean() > capacity_cap:
                break
    else:
        while True:
            s_lo = s
            s *= 2.0
            s_hi = s
            if calc_q_capacity_iter(sim_opts_gen, s).mean() < capacity_cap:
                break

    if verbose:
        logTime('s_hi = {}, s_lo = {}'.format(s_hi, s_lo))

    # Step 2: Keep bisecting on 's' until we arrive at a close enough solution.
    while True:
        s = (s_hi + s_lo) / 2.0
        new_capacity = calc_q_capacity_iter(sim_opts_gen, s).mean()

        if verbose:
            logTime('new_capacity = {}, s = {}'.format(new_capacity, s))

        if abs(new_capacity - capacity_cap) / capacity_cap < tol:
            # Have converged
            break
        elif new_capacity > capacity_cap:
            s_lo = s
        else:
            s_hi = s

    # Step 3: Return
    return s


import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt



def curve2str(curve, divisor, span, is_global, is_elastic, x_title='x', y_title='y'):
    assert curve.ndim == 1 and span > 9 # must be a vector
    try:
        assert os.get_terminal_size().columns > span + 10 + 5  # ensure that curve is not too long to display
    except OSError:
        pass

    line_type = {'ascent': '/', 'descent': '\\', 'vertical': '|', 'horizontal': '_'}
    if span < curve.size:
        if is_global:
            indices = [round(i * curve.size / span) for i in range(span)]
            curve = curve[indices]
            indices = [idx+1 for idx in indices]
        else:
            indices = [curve.size - i for i in range(span, 0, -1)]
            curve = curve[-span:]
    else:
        indices = [i for i in range(1, span+1)]
    y_max = curve.max()
    y_min = curve.min()
    delta = (y_max - y_min) / divisor
    if delta == 0.:
        grid = [[10 * ' ' + ' ┃ ', span * ' ', '\n'] for i in range(1, divisor + 1)]
        grid.append([10 * ' ' + ' ▲ ', span * ' ', '\n'])
    else:
        if is_elastic:
            quant = np.clip(np.floor((curve - y_min) / delta).astype(np.int8), 0, divisor-1)
            hist = np.zeros(divisor)
            qualified = np.ones(divisor, dtype=np.int8) # the merged segments are unqualified
            increment = 1. / quant.size
            # build histogram for bins along the vertical axis
            for q in quant:
                hist[q] += increment
            ascend = np.argsort(hist) # sort vertical segments in ascending order
            portion = 1. / divisor
            merged = 0 # the number of merged segments
            segment = 0 # the number of segments left which ever get involved in merging
            contig = 0 # the number of contiguous small segments
            sum_h = 0
            # merge rarely plotted areas
            last = -1 # where the last merged segment ends
            for k, h in enumerate(hist):
                sum_h += h
                if sum_h < portion and k < divisor-1:
                    contig += 1
                elif k == divisor-1:
                    stop = k
                    if h < portion and contig > 0:
                        stop += 1
                    if h >= portion and contig == 1:
                        contig = 0
                    qualified[k - contig: stop] *= 0
                    merged += stop - (k - contig)
                    if stop - (k - contig) > 0 and (last < 0 or last != k-contig):
                        segment += 1
                else:
                    if contig > 1:
                        stop = k
                        if h < portion:
                            stop += 1
                        qualified[k-contig : stop] *= 0
                        merged += stop - (k - contig)
                        if last < 0 or last != k - contig:
                            segment += 1
                        last = stop
                        contig = 0
                        sum_h = 0
                    elif h < portion:
                        sum_h = h
                        contig = 1
                    else:
                        contig = 0
                        sum_h = 0
            # replot curves
            delimiter = [0]
            quot = (merged - segment) % (divisor - merged)
            univ = (merged - segment) // (divisor - merged)
            qualified *= univ + 1 # assign the additional sub-segment to qualified segments by average
            if quot > 0:
                filled = 0
                for a in ascend[::-1]:
                    if filled == quot:
                        break
                    if qualified[a] > 0:
                        qualified[a] += 1
                        filled += 1
            m_ = -1 # start position of the current merged segment
            _m = -1 # ending position of the current merged segment
            quant = np.zeros_like(quant)
            for k, q in enumerate(qualified):
                if q == 0:
                    m_ = k if m_<0 else m_
                    _m = k
                else:
                    if _m>=0:
                        delimiter.append((_m + 1) * delta)
                        quant[curve - y_min - delimiter[-2] > 0] = len(delimiter) - 1
                    for j in range(q):
                        delimiter.append(k * delta + (j+1) * delta/q)
                        quant[curve - y_min - delimiter[-2] > 0] = len(delimiter) - 1
                    m_ = -1
                    _m = -1
            if _m >= 0:
                delimiter.append((_m + 1) * delta)
                quant[curve - y_min - delimiter[-2] > 0] = len(delimiter) - 1
            delimiter = delimiter[1:]
        else:
            quant = np.round((curve - y_min) / delta).astype(np.int8)
            delimiter = [i * delta for i in range(1, divisor+1)]

        grid = [[f'{y_min + d:>10.3f} ┃ ', span * ' ', '\n'] for d in delimiter]
        grid.append([10 * ' ' + ' ▲︎ ', span * ' ', '\n'])
        # draw the curve
        for i in range(curve.size-1):
            prev = quant[i]
            curr = quant[i + 1]
            if prev > curr:
                grid[prev - 1][1] = grid[prev - 1][1][:i] + line_type['descent'] + grid[prev - 1][1][i + 1:]
                for j in range(1, prev - curr):
                    grid[prev - 1 - j][1] = grid[prev - 1 - j][1][:i] + line_type['vertical'] + grid[prev - 1 - j][1][
                                                                                                i + 1:]
            elif prev < curr:
                grid[prev][1] = grid[prev][1][:i] + line_type['ascent'] + grid[prev][1][i + 1:]
                for j in range(1, curr - prev):
                    grid[prev + j][1] = grid[prev + j][1][:i] + line_type['vertical'] + grid[prev + j][1][i + 1:]
            else:
                grid[prev][1] = grid[prev][1][:i] + line_type['horizontal'] + grid[prev][1][i + 1:]

    # initialize axis
    cstr = ''
    cstr += 10 * ' ' + ' %s\n'%y_title
    for i in range(divisor, -1, -1):
        cstr += ''.join(grid[i])
    cstr += f'{y_min:>10.3f} ┗━' + span * '━' + ' ► %s\n'%x_title
    x_domain = (10+3) * ' '
    for i in range(0, len(indices), 5):
        idx = indices[i]
        if idx<1e3:
                x_domain += f'{idx:<4d} '
        elif idx<1e4:
                x_domain += f'{idx/1e3:<3.1f}K '
        elif idx<1e6:
                x_domain += f'{round(idx/1e3):<3d}K '
        elif idx<1e7:
                x_domain += f'{idx/1e6:<3.1f}M '
        elif idx<1e9:
                x_domain += f'{round(idx/1e6):<3d}M '
    cstr += x_domain+'\n'

    return cstr

def join_imgs(imgs, nrow, ncol):
    N, H, W, C = imgs.shape
    assert N == nrow*ncol, 'NEBULAE ERROR ៙ the number of images does not match cells.'
    assert N > 1, 'NEBULAE ERROR ៙ one image does not need to be pieced together.'
    margin_h = max(1, H//20)
    margin_w = max(1, W//20)
    canvas = np.zeros((margin_h*(nrow+1) + H*nrow, margin_w*(ncol+1) + W*ncol, C))
    for c in range(ncol):
        for r in range(nrow):
            y = margin_h*(r+1) + H*r
            x = margin_w*(c+1) + W*c
            canvas[y:y+H, x:x+W] = imgs[r*ncol + c]
    return canvas


def viz_flow(flow: np.ndarray, invalid_thr: float = 1e6):
    """Convert flow map to RGB image.

    Args:
        flow (ndarray): Array of optical flow.
        invalid_thr (float): Values above this threshold will be marked as
            unknown and thus ignored.

    Returns:
        ndarray: RGB image that can be visualized.
    """
    assert flow.ndim == 3 and flow.shape[-1] == 2
    color_wheel = _get_color_wheel()
    assert color_wheel.ndim == 2 and color_wheel.shape[1] == 3
    num_bins = color_wheel.shape[0]

    dx = flow[:, :, 0].copy()
    dy = flow[:, :, 1].copy()

    invalid_idx = (np.isnan(dx) | np.isnan(dy) | (np.abs(dx)>invalid_thr) | (np.abs(dy)>invalid_thr))
    dx[invalid_idx] = 0
    dy[invalid_idx] = 0

    rad = np.sqrt(dx**2 + dy**2)
    if np.any(rad > np.finfo(float).eps):
        max_rad = np.max(rad)
        dx /= max_rad
        dy /= max_rad

    rad = np.sqrt(dx**2 + dy**2)
    assert rad <= 1
    angle = np.arctan2(-dy, -dx) / np.pi

    bin_real = (angle + 1) / 2 * (num_bins - 1)
    bin_left = np.floor(bin_real).astype(int)
    bin_right = (bin_left + 1) % num_bins
    w = (bin_real - bin_left.astype(np.float32))[..., None]
    flow_img = (1 - w) * color_wheel[bin_left, :] + w * color_wheel[bin_right, :]
    
    flow_img = 1 - rad * (1 - flow_img)
    flow_img[invalid_idx, :] = 0

    return flow_img


def _get_color_wheel(bins=None):
    """Build a color wheel.

    Args:
        bins(list or tuple, optional): Specify the number of bins for each
            color range, corresponding to six ranges: red -> yellow,
            yellow -> green, green -> cyan, cyan -> blue, blue -> magenta,
            magenta -> red. [15, 6, 4, 11, 13, 6] is used for default
            (see Middlebury).

    Returns:
        ndarray: Color wheel of shape (total_bins, 3).
    """
    if bins is None:
        bins = [15, 6, 4, 11, 13, 6]
    assert len(bins) == 6

    RY, YG, GC, CB, BM, MR = tuple(bins)

    ry = [1, np.arange(RY) / RY, 0]
    yg = [1 - np.arange(YG) / YG, 1, 0]
    gc = [0, 1, np.arange(GC) / GC]
    cb = [0, 1 - np.arange(CB) / CB, 1]
    bm = [np.arange(BM) / BM, 0, 1]
    mr = [1, 0, 1 - np.arange(MR) / MR]

    num_bins = RY + YG + GC + CB + BM + MR
    color_wheel = np.zeros((3, num_bins), dtype=np.float32)
    col = 0
    for i, color in enumerate([ry, yg, gc, cb, bm, mr]):
        for j in range(3):
            color_wheel[j, col:col + bins[i]] = color[j]
        col += bins[i]

    return color_wheel.T


def plot_in_one(crv_names, crv_files, dst_path):
    assert len(crv_names)==len(crv_files), 'NEBULAE ERROR ៙ the number of files does not match names.'
    assert len(crv_names) > 1, 'NEBULAE ERROR ៙ one curve does not need to be drawn together.'
    palette = ['#F08080', '#00BFFF', '#FFFF00', '#2E8B57', '#6A5ACD', '#FFD700', '#808080']
    i = 0
    for n, f in zip(crv_names, crv_files):
        data = pd.read_csv(f, header=None).values
        plt.plot(data[:,0], data[:,1], c=palette[i % len(palette)], label=n)
        i += 1
    plt.legend()
    plt.grid(True)
    plt.savefig(dst_path)
    plt.close()


def sprawl(root, desc=None, body='', branch=(), depth=-1, layer=0, outfile:object=None):
    if isinstance(root, str) and os.path.isdir(root):
        if layer == 0:
            line = '|⊻| ' + os.path.basename(root)
            if outfile is not None:
                outfile.write(line + '\n')
            else:
                print(line)
        traverse = os.listdir(root)
        for i, f in enumerate(traverse):
            if i < len(traverse) - 1:
                line = (layer + 1) * 2 * ' ' + '├─' + f
                if outfile is not None:
                    outfile.write(line + '\n')
                else:
                    print(line)
            else:
                line = (layer + 1) * 2 * ' ' + '└─' + f
                if outfile is not None:
                    outfile.write(line + '\n')
                else:
                    print(line)
            if os.path.isdir(os.path.join(root, f)) and (depth<0 or layer<depth):
                sprawl(os.path.join(root, f), desc, body, branch, depth, layer + 1, outfile)
    else:
        if layer == 0:
            itself = root if desc is None else getattr(root, desc)
            line = '|⊻| ' + itself + ': ' + ' '.join([f'{getattr(root, b)}' for b in branch])
            if outfile is not None:
                outfile.write(line + '\n')
            else:
                print(line)
        traverse = getattr(root, body)
        for i, f in enumerate(traverse):
            itself = f if desc is None else getattr(f, desc)
            if i < len(traverse) - 1:
                line = (layer + 1) * 2 * ' ' + '├─' + itself + ': ' + ' '.join([f'{b}={getattr(f, b)}' for b in branch])
                if outfile is not None:
                    outfile.write(line + '\n')
                else:
                    print(line)
            else:
                line = (layer + 1) * 2 * ' ' + '└─' + itself + ': ' + ' '.join([f'{b}={getattr(f, b)}' for b in branch])
                if outfile is not None:
                    outfile.write(line + '\n')
                else:
                    print(line)
            if hasattr(root, body) and (depth<0 or layer<depth):
                sprawl(f, desc, body, branch, depth, layer + 1, outfile)
    # close file object
    if outfile is not None and layer == 0:
        outfile.close()
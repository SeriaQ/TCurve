<p align="center">
  <img src="https://ooo.0x0.ooo/2025/03/19/OSKUBC.png" alt="tcurve-icon.png" width = "180" height = "120" />
</p>
<h1 align="center">TCurve</h1>

<p align="center">
  <b> A sleek progress bar tool </b><br>
  For better experience of printing on the terminal.
</p>


<p align="center">
  <img src="https://img.shields.io/pypi/v/tcurve?color=blue&label=Version" alt="Version">
  <img src="https://img.shields.io/github/stars/SeriaQ/TCurve?style=social" alt="GitHub Repo Stars">
  <img src="https://img.shields.io/badge/Made%20with-Python-blue" alt="Python">
  <img src="https://img.shields.io/badge/License-MIT-green" alt="MIT License">
</p>


------

## 🚀 Spotlight

📈 **Fascinating Dashboard**

It shows visually appealing progress bars and draws metric based curves in real-time.

[![THAIh9.gif](https://s4.ax1x.com/2022/01/03/THAIh9.gif)](https://imgtu.com/i/THAIh9)



------

## ⚡ Quick Start

You can simply take it as a wrapper or help you plot curves.

```python
from tcurve import Dash as tcd
from time import sleep

# a simple wrapper
for i in tcd(range(10)):
    time.sleep(0.5)

# wrap a generator
for i in tcd(enumerate(range(30))):
    time.sleep(0.3)

# with keyword arguments
for i,n in tcd(enumerate(range(30)), format={'number': [lambda x:x[1], CUSTOM]}, epoch=2, mpe=30, stage='COUNT', interv=1, wipe=False):
    time.sleep(0.3)

# in a complicated manner
dash = tcd(format={'Acc': ['.1f', PERCENT]})
unit_acc = [0.012, 0.045, 0.134, 0.189, 0.234, 0.278, 0.345, 0.378, 0.456, 0.423, 0.51, 0.599, 0.623, 0.62, 0.7] # create a fake array for this tutorial
fake_acc = unit_acc + unit_acc[::-1] + unit_acc + unit_acc[::-1] + unit_acc + unit_acc[::-1]
for i, a in enumerate(fake_acc):
    time.sleep(0.1)
    dash({'Accuracy': a}, 0, i, len(fake_acc))
```



------

## 🔥 Dive Deeper

Let's take the last example in previous part to show how could you use more arguments for delicate control.

```python
# below is the common setting
unit_acc = [0.012, 0.045, 0.134, 0.189, 0.234, 0.278, 0.345, 0.378, 0.456, 0.423, 0.51, 0.599, 0.623, 0.62, 0.7] # create a fake array for this tutorial
flat_acc = [0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5]
fake_acc = 10 * (unit_acc + unit_acc[::-1] + flat_acc)
```

We only take this for-loop to demonstrate. First, you can use is_global=True to plot the entire curve.

```python
dash = tcd(format={'Acc': ['.1f', PERCENT]})
for i, a in enumerate(fake_acc):
    time.sleep(0.1)
    dash({'Accuracy': a}, 0, i, len(fake_acc), is_global=True)
```

Make is_elastic=True to dynamically stretch or squeeze the vertical axis.

```python
dash = tcd(format={'Acc': ['.1f', PERCENT]})
for i, a in enumerate(fake_acc):
    time.sleep(0.1)
    dash({'Accuracy': a}, 0, i, len(fake_acc), is_global=False)
```

Make is_elastic=True to dynamically stretch or squeeze the vertical axis so that the fluctuation of curves is prominent enough to be observed.

```python
dash = tcd(format={'Acc': ['.1f', PERCENT]})
for i, a in enumerate(fake_acc):
    time.sleep(0.1)
    dash({'Accuracy': a}, 0, i, len(fake_acc), is_elastic=True)
```

When you have several variables, set in_loop and last_for to switch among them.

*e.g* in_loop=(0, 1), last_for=5 means dashboard is going to show curves of var[0] and var[1] in turns. The displayed curve changes every 5 steps.

```python
dash = tcd(format={'Acc': ['.1f', PERCENT], 'Level': ['.d', RAW]})
for i, a in enumerate(fake_acc):
    time.sleep(0.1)
    dash({'Accuracy': a, 'Level': i*i}, 0, i, len(fake_acc), in_loop=(0, 1), last_for=5)
```

What's more, you can even draw the gray image on the terminal.

```python
dash = Dash(format={'I': [lambda *x:1, IMAGE]})
for i, img in enumerate(images):
    time.sleep(0.1)
    # read images here
    dash({'I': img}, 0, i, len(images))
```

Try to squint at the right side. :D

<p align="center">
  <img src="https://ooo.0x0.ooo/2025/03/20/OSgJ3l.jpg" alt="donut-photo.jpg" width = "280" height = "280" />
  <img src="https://ooo.0x0.ooo/2025/03/20/OSgRig.png" alt="donut-chars.png" width = "280" height = "280" />
</p>




------

## 📦 Installation

Install tcurve via pip

```sh
pip install tcurve
```

Install the following libs to access full functions.

- numpy
- pandas
- matplotlib
- seaborn



------

## ❤️ Support

If you find TCurve helpful, please give it a ⭐ on GitHub! ▶️ https://github.com/SeriaQ/TCurve
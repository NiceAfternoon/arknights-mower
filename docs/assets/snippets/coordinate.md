In \[1\]:

```
from arknights_mower.utils.solver import BaseSolver
```

In \[2\]:

```
pos1 = (50, 30)
pos2 = (80, 60)
scope = (pos1, pos2)
```

In \[3\]:

```
BaseSolver.get_pos(scope)
```

Out\[3\]:

```
(65, 45)
```

In \[4\]:

```
BaseSolver.get_pos(scope, x_rate=0.2, y_rate=0.8)
```

Out\[4\]:

```
(56, 54)
```

In \[5\]:

```
from arknights_mower.utils.vector import va, vs, sa
```

In \[6\]:

```
va(pos1, pos2)
```

Out\[6\]:

```
(130, 90)
```

In \[7\]:

```
vs(pos1, pos2)
```

Out\[7\]:

```
(-30, -30)
```

In \[8\]:

```
pos3 = (90, 40)
sa(scope, pos3)
```

Out\[8\]:

```
((140, 70), (170, 100))
```
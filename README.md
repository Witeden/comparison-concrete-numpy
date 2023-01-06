# Integers from 1 to 15 bits
Since LUT is supported up to 16 bits, the operation $x \leq y$ can be computed with a single
LUT applied to $x-y$.

# 16 bits Integers
Doing a substraction on 16-bits integers output a 17 bits integer, hence the previous solution no longer works. Instead, I chose to extract the most significant bit (MSB) `b1` and `b2` of each integer using `right_shift` operation. Then, I extract the other bits using `and` operation. 
We can then treat the MSBs first, and then compare the difference $r1 - r2$ (which is possible because it is a 16-bits integer).

# Inequality comparisons
Let us take the case of $x \leq y$ (other inequelaties will work in a similar way).
$x \leq y$ is equivalent to $(b1 \less b2) or [(b1==b2) and (r1 \leq r2)]$. The trick is to compute this expression as $b2 + (1-b1) + (r1 \leq r2)$, which takes values 2 or 3 when $x \leq y$ and 0 or 1 otherwise. Hence, the comparison itself only needs 2 LUT: one for $r1 \leq r2$ and one to check if the final expression is greater than 1.

# Equality comparisons
As opposed to inequality comparisons, I did not find a suitable expression to avoid one more LUT. Here, I have to compare `b1` and `b2`. Then, I evaluate $(b1==b2) + (r1==r2)$ and check whether it is equalt to 2 or not.

# Implementation
Since the intermediate operations described previously produce several output type, I thought it would be easier to directly modify the definition of the functions in `concrete/numpy/tracing/tracer.py`. The other files I modified are `concrete/numpy/mlir/node_converter.py` (to add the `_convert` functions) and `concrete/numpy/mlir/graph_converter.py` (to add appropriate assert in `check_node_convertibility`).
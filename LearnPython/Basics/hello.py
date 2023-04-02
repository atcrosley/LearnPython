print("hello world")
# Summary
# resource docs.python.org
# datatypes str - string, int - integers
# functions (action) print(), input()
# variables ex. name = input("what's your name?")
# methods(subtype of function denoted by .) - name.title().strip().split()
# Define a function with keyword def
# scope - where you define your variables matter. If you define a var inside a function it lives in the scope of that function and has to passed outside of that function if you want to use it elsewhere
# return - using return in a function will return a result back to wherever the function was called

# print - first example of a function
# ("hello world") is called an argument
# input("What's your name? ")
# This function asks your user for an input
# We can add a vairable to use as a container for our return value. We will call our variable name
"""
Another way to comment in python is to use 3 parathesis 
"""
name = input("What's your name? ")
# to use the user's input we will use + to concatenate our string and input
print("Hello, " + name)
# We can look at docs.python.org for documentation on functions and see that the arguments for print are print(*objects, sep=' ', end='\n') *objects means we can put as many arguments as we like, sep = seperator which gives a space between or objects and end='\n' means the end of the function will give us a new line
# you can override a parameters default value
print("Hello, ", end='')
print(name)
# notice when you run the code it returns on same line

# There are different types of parameters. Positional parameters have to be given to the function in order.
# Named parameters like end or sep are optional. Used to override default parameters.
# Another way to solve this problem
print(f"Hello, {name}")
# f before the first parameter tells python this is special sytax. Curly brackets identify the input

# The . denotes a method applied to the string. In this case strip takes away the white spaces leaving only the str
name = input("What's your name? ")
name = name.strip()
name = name.title()
# The variable name has been updated to not include spaces to the left or right of str
print(f"hello, {name}")

# split users name into first name and last name
# first, last = name.split(" ")
# print(f"hello, {first}")

"""
Int - integers 
float - floating point = decimal
+, -, /, *, %(remainder), **(power)
"""

x = (input("what's the value of x?"))
y = (input("what's the value of y?"))
z = round(float(x) + float(y))

print(z)

"""
Defining a function 
"""

# these two functions demonstrate how to pass a variable out of the scope of one function to another. In this case we are able to use name given by our user from main function in our hello function. Notice the name of variable 'name' is now being called 'to' because it is being used as the argument for the parameter of function hello world


def main():
    name = input("What's your name?")
    hello(name)


def hello(to="world"):
    print("hello", to)


main()
"""
Scope lesson 
"""


def math():
    x = int(input("Value of x?"))
    print("The square of x is", square(x))


def square(n):
    return n*n


math()
